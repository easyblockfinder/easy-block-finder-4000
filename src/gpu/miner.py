"""OpenCL SHA-256d miner — NVIDIA / AMD / Intel OpenCL. No CUDA Toolkit / no CPU mining."""

from __future__ import annotations

import logging
import struct
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from monitor.gpu_devices import classify_vendor

log = logging.getLogger(__name__)

# Default; can be selected with a short benchmark in init
LOCAL_SIZE = 256
CANDIDATE_LOCAL_SIZES = (64, 128, 256, 512)


class GpuUnavailableError(RuntimeError):
    """OpenCL GPU is unavailable (no CUDA/CPU fallback)."""


@dataclass
class SearchResult:
    """The result of a kernel call — the speed calculation is performed via scanned."""

    hits: list[int]
    scanned: int
    global_size: int
    local_size: int
    start_nonce: int
    raw_hit_count: int = 0  # atomic counter (before buffer limit)
    truncated: bool = False
    # Batch minimum PoW hash. WARNING: RAW SHA-256d digest bytes (NOT display/BE order);
    # do not pass best_hash_be.hex() to hash_be_hex_to_int — use best_hash_be_hex.
    best_hash_be: Optional[bytes] = None
    best_nonce: Optional[int] = None

    @property
    def best_hash_be_hex(self) -> Optional[str]:
        """Explorer/PoW form (digest[::-1] hex) == mining hash_be_hex; safe for hash_be_hex_to_int."""
        return None if not self.best_hash_be else self.best_hash_be[::-1].hex()

    @property
    def best_hash_int(self) -> Optional[int]:
        """PoW value: int.from_bytes(digest[::-1], 'big')."""
        return None if not self.best_hash_be else int.from_bytes(self.best_hash_be[::-1], "big")


def target_to_le_words(target: int) -> list[int]:
    return list(struct.unpack("<8I", target.to_bytes(32, "little")))


def header_tail_words(header: bytes) -> tuple[int, int, int, int]:
    if len(header) != 80:
        raise ValueError("80 bayt header gerekli.")
    return struct.unpack(">4I", header[64:80])


# PCI / topology extensions (OpenCL index ≠ NVML index)
_CL_DEVICE_PCI_BUS_ID_NV = 0x4008
_CL_DEVICE_TOPOLOGY_AMD = 0x4037
_CL_DEVICE_PCI_BUS_ID_KHR = 0x4251
_CL_DEVICE_PCI_SLOT_ID_KHR = 0x4252
_CL_DEVICE_TOPOLOGY_TYPE_PCIE_AMD = 1


def _opencl_pci_bus_number(device) -> Optional[int]:
    """PCI bus number from NVIDIA / AMD / KHR extensions."""
    try:
        return int(device.get_info(_CL_DEVICE_PCI_BUS_ID_NV))
    except Exception:
        pass
    try:
        return int(device.get_info(_CL_DEVICE_PCI_BUS_ID_KHR))
    except Exception:
        pass
    try:
        topo = device.get_info(_CL_DEVICE_TOPOLOGY_AMD)
        if hasattr(topo, "pcie"):
            return int(getattr(topo.pcie, "bus", 0))
        if isinstance(topo, (bytes, bytearray)) and len(topo) >= 22:
            t = int.from_bytes(topo[0:4], "little")
            if t == _CL_DEVICE_TOPOLOGY_TYPE_PCIE_AMD:
                return int(topo[21])
    except Exception:
        pass
    return None


def _nvml_bus_number(bus_id: str) -> Optional[int]:
    """'00000000:01:00.0' → 1; None if unsuccessful."""
    text = (bus_id or "").strip().upper()
    if not text:
        return None
    try:
        # domain:bus:dev.fn
        parts = text.split(":")
        if len(parts) >= 2:
            return int(parts[1], 16)
    except ValueError:
        pass
    return None


def _pick_opencl_gpu(cl, prefer_bus_id: Optional[str] = None):
    """Pick any OpenCL GPU (NVIDIA / AMD / Intel); match prefer_bus_id when set."""
    try:
        platforms = cl.get_platforms()
    except Exception as exc:
        raise GpuUnavailableError(
            f"Failed to retrieve OpenCL platform list: {exc}. "
            "OpenCL may be disabled in the GPU driver, or OpenCL.dll may be corrupted."
        ) from exc

    if not platforms:
        raise GpuUnavailableError(
            "No OpenCL platform. Install/reinstall the GPU driver "
            "(NVIDIA / AMD / Intel) with OpenCL support."
        )

    gpu_devices = []
    notes = []
    for p in platforms:
        try:
            devs = p.get_devices(device_type=cl.device_type.GPU)
        except Exception as exc:
            notes.append(f"{p.name}: device list error ({exc})")
            continue
        for d in devs:
            vendor_raw = d.vendor or ""
            name = d.name or ""
            vendor = classify_vendor(vendor_raw, name)
            pci = _opencl_pci_bus_number(d)
            notes.append(
                f"{p.name} / {name} ({vendor_raw}) vendor={vendor} pci_bus={pci}"
            )
            if vendor == "unknown":
                # Still allow unknown discrete GPUs advertised as GPU type
                pass
            gpu_devices.append((p, d, pci, vendor))

    if not gpu_devices:
        detail = "; ".join(notes) if notes else "no devices"
        raise GpuUnavailableError(
            f"No OpenCL GPU found. Seen: {detail}. "
            "CPU mining is not enabled for BTC/BCH."
        )

    want = _nvml_bus_number(prefer_bus_id or "")
    if want is not None:
        for p, d, pci, _vendor in gpu_devices:
            if pci is not None and int(pci) == int(want):
                return p, d
        # If there is no PCI extension / if it does not match: secure fallback on a single card
        if len(gpu_devices) == 1:
            return gpu_devices[0][0], gpu_devices[0][1]
        raise GpuUnavailableError(
            f"OpenCL PCI bus did not match (requested bus={prefer_bus_id}, "
            f"pci_bus={want}). Index equality is not reliable in multi-GPU; "
            "PCI-based driver or correct bus selection required."
        )

    if len(gpu_devices) > 1 and want is None:
        raise GpuUnavailableError(
            "There are multiple OpenCL GPUs; gpu_bus_id / PCI mapping is required "
            "(the first device is not auto-selected)."
        )
    p, d, _pci, _vendor = gpu_devices[0]
    return p, d


# Back-compat alias for tests / callers
_pick_nvidia_gpu = _pick_opencl_gpu


class GpuMiner:
    def __init__(
        self,
        autotune_local: bool = True,
        *,
        prefer_bus_id: Optional[str] = None,
    ) -> None:
        self._cl = None
        self._ctx = None
        self._queue = None
        self._kernel = None
        self._kernel_hash = None
        self._device = None
        self._device_name = ""
        self._prefer_bus_id = (prefer_bus_id or "").strip() or None
        self._local_size = LOCAL_SIZE
        self._d_ms = None
        self._d_tgt = None
        self._d_out = None
        self._d_cnt = None
        self._d_best = None
        self._host_best = np.zeros(10, dtype=np.uint32)  # key[8], nonce, lock
        # At Diff=1, there can be many shares per batch; it can reduce the 16-slot block candidate
        self._max_hits = 256
        self._host_ms = np.zeros(8, dtype=np.uint32)
        self._host_tgt = np.zeros(8, dtype=np.uint32)
        self._host_out = np.zeros(self._max_hits, dtype=np.uint32)
        self._host_cnt = np.zeros(1, dtype=np.uint32)
        # Host→GPU copy cache (reload unless midstate / target changes)
        self._uploaded_ms: Optional[bytes] = None
        self._uploaded_tgt: Optional[int] = None
        self._init_opencl(autotune_local=autotune_local)

    @property
    def device_name(self) -> str:
        return self._device_name

    @property
    def local_size(self) -> int:
        return self._local_size

    def _init_opencl(self, autotune_local: bool = True) -> None:
        try:
            import pyopencl as cl
        except ImportError as exc:
            raise GpuUnavailableError(
                "pyopencl is not installed (~3 MB)."
                'Kurulum: python -m pip install "pyopencl>=2024"'
            ) from exc

        self._cl = cl
        platform, device = _pick_opencl_gpu(cl, prefer_bus_id=self._prefer_bus_id)
        self._device = device
        vendor = classify_vendor(getattr(device, "vendor", "") or "", device.name or "")
        self._device_name = device.name.strip()
        if vendor and vendor != "unknown":
            self._device_name = f"{self._device_name} [{vendor}]"
        pci = _opencl_pci_bus_number(device)
        if pci is not None:
            self._device_name = f"{self._device_name} (OpenCL pci_bus={pci})"
        try:
            self._ctx = cl.Context(devices=[device])
            self._queue = cl.CommandQueue(self._ctx)
        except Exception as exc:
            raise GpuUnavailableError(
                f"Failed to open OpenCL context ({self._device_name}): {exc}"
            ) from exc

        source = Path(__file__).with_name("sha256d.cl").read_text(encoding="utf-8")
        program = cl.Program(self._ctx, source)
        try:
            # No fast-relaxed-math — SHA-256 must be bit-precise
            program.build(options=["-cl-std=CL1.2"])
        except Exception as exc:
            log_txt = ""
            try:
                log_txt = program.get_build_info(device, cl.program_build_info.LOG)
            except Exception:
                pass
            raise GpuUnavailableError(
                f"OpenCL kernel derlenemedi: {exc}\n{log_txt}"
            ) from exc

        self._kernel = program.sha256d_search
        self._kernel_hash = program.sha256d_hash_nonces
        mf = cl.mem_flags
        self._d_ms = cl.Buffer(self._ctx, mf.READ_ONLY, 32)
        self._d_tgt = cl.Buffer(self._ctx, mf.READ_ONLY, 32)
        self._d_out = cl.Buffer(self._ctx, mf.WRITE_ONLY, 4 * self._max_hits)
        self._d_cnt = cl.Buffer(self._ctx, mf.READ_WRITE, 4)
        self._d_best = cl.Buffer(self._ctx, mf.READ_WRITE, 40)

        if autotune_local:
            self._local_size = self._autotune_local_size()
        log.info(
            "OpenCL ready: %s local=%s (%s / %s)",
            self._device_name,
            self._local_size,
            platform.name,
            device.version,
        )

    def _autotune_local_size(self) -> int:
        """Short benchmark — the local size that gives the highest actual H/s."""
        # Warm-up + steady-state work for measurement
        from mining.bitcoin import bits_to_target, midstate_from_header

        genesis = bytes.fromhex(
            "0100000000000000000000000000000000000000000000000000000000000000"
            "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
            "4b1e5e4a29ab5f49ffff001d1dac2b7c"
        )
        ms = midstate_from_header(genesis)
        net = bits_to_target("1d00ffff")
        best_ls = LOCAL_SIZE
        best_rate = 0.0
        n = 1_048_576
        for ls in CANDIDATE_LOCAL_SIZES:
            self._local_size = ls
            try:
                # warm-up
                self.search(ms, genesis, net, 0, n // 4)
                t0 = time.perf_counter()
                r = self.search(ms, genesis, net, 0, n)
                dt = max(1e-6, time.perf_counter() - t0)
                rate = r.scanned / dt
                log.info("autotune local=%s -> %.2f MH/s", ls, rate / 1e6)
                if rate > best_rate:
                    best_rate = rate
                    best_ls = ls
            except Exception as exc:
                log.warning("autotune local=%s skipped: %s", ls, exc)
        self._local_size = best_ls
        return best_ls

    def close(self) -> None:
        self._d_ms = self._d_tgt = self._d_out = self._d_cnt = self._d_best = None
        self._kernel = None
        self._kernel_hash = None
        self._queue = None
        self._ctx = None
        self._device = None
        self._uploaded_ms = None
        self._uploaded_tgt = None

    def search(
        self,
        midstate: bytes,
        header80: bytes,
        share_target: int,
        start_nonce: int,
        count: int,
        max_hits: int = 256,
        track_best: bool = True,
    ) -> SearchResult:
        """
        Tek kernel: [start_nonce, start_nonce+count) paralel.
        Only nonces that beat the target are returned to the host.
        raw_hit_count > max_hits sets truncated=True (overflow slots may be lost).
        """
        if count <= 0:
            return SearchResult([], 0, 0, self._local_size, start_nonce)
        if len(midstate) != 32:
            raise ValueError("The midstate must be 32 bytes.")
        ls = int(self._local_size)
        if track_best and (ls <= 0 or ls > 512 or (ls & (ls - 1)) != 0):
            raise ValueError(
                f"track_best requires a power-of-two local_size <= 512 (got {ls})."
            )
        if start_nonce + count - 1 > 0xFFFFFFFF:
            count = 0xFFFFFFFF - start_nonce + 1

        cl = self._cl
        assert cl is not None and self._ctx is not None and self._queue is not None
        assert self._kernel is not None
        assert self._d_ms is not None and self._d_tgt is not None
        assert self._d_out is not None and self._d_cnt is not None
        assert self._d_best is not None

        if max_hits != self._max_hits:
            self._max_hits = max_hits
            self._host_out = np.zeros(max_hits, dtype=np.uint32)
            self._d_out = cl.Buffer(self._ctx, cl.mem_flags.WRITE_ONLY, 4 * max_hits)

        t0, t1, t2, _ = header_tail_words(header80)

        # To GPU only when midstate / target changes
        if midstate != self._uploaded_ms:
            self._host_ms[:] = struct.unpack("<8I", midstate)
            cl.enqueue_copy(self._queue, self._d_ms, self._host_ms)
            self._uploaded_ms = bytes(midstate)
        if share_target != self._uploaded_tgt:
            self._host_tgt[:] = target_to_le_words(share_target)
            cl.enqueue_copy(self._queue, self._d_tgt, self._host_tgt)
            self._uploaded_tgt = int(share_target)

        self._host_cnt[0] = 0
        cl.enqueue_copy(self._queue, self._d_cnt, self._host_cnt)
        if track_best:
            self._host_best[:8] = 0xFFFFFFFF
            self._host_best[8:] = 0
            cl.enqueue_copy(self._queue, self._d_best, self._host_best)

        self._kernel.set_args(
            self._d_ms,
            np.uint32(t0),
            np.uint32(t1),
            np.uint32(t2),
            np.uint32(int(start_nonce) & 0xFFFFFFFF),
            self._d_tgt,
            self._d_out,
            self._d_cnt,
            np.uint32(self._max_hits),
            np.uint32(int(count)),
            self._d_best,
            np.uint32(1 if track_best else 0),
        )

        local = int(self._local_size)
        global_size = ((int(count) + local - 1) // local) * local
        cl.enqueue_nd_range_kernel(
            self._queue, self._kernel, (global_size,), (local,)
        )
        cl.enqueue_copy(self._queue, self._host_cnt, self._d_cnt)
        if track_best:
            cl.enqueue_copy(self._queue, self._host_best, self._d_best)
        self._queue.finish()

        raw_n = int(self._host_cnt[0])
        truncated = raw_n > self._max_hits
        n = min(raw_n, self._max_hits)
        hits: list[int] = []
        if n > 0:
            cl.enqueue_copy(self._queue, self._host_out, self._d_out)
            self._queue.finish()
            hits = [int(x) for x in self._host_out[:n].tolist()]

        best_hash_be: Optional[bytes] = None
        best_nonce: Optional[int] = None
        if track_best:
            key = [int(x) for x in self._host_best[:8]]
            if any(w != 0xFFFFFFFF for w in key):
                # kernel key = display-order BE words; raw digest bytes are the reverse
                best_hash_be = struct.pack(">8I", *key)[::-1]
                best_nonce = int(self._host_best[8])

        return SearchResult(
            hits=hits,
            scanned=int(count),
            global_size=global_size,
            local_size=local,
            start_nonce=int(start_nonce) & 0xFFFFFFFF,
            raw_hit_count=raw_n,
            truncated=truncated,
            best_hash_be=best_hash_be,
            best_nonce=best_nonce,
        )

    def hash_nonces(
        self,
        midstate: bytes,
        header80: bytes,
        nonces: list[int],
    ) -> list[bytes]:
        """
        Compute SHA-256d digest per nonce on GPU (32 bytes, same layout as hash256).
        Result is read from GPU buffers — not recomputed on CPU and passed off as GPU.
        """
        if not nonces:
            return []
        if len(midstate) != 32 or len(header80) != 80:
            raise ValueError("midstate/header size is incorrect.")

        cl = self._cl
        assert cl is not None and self._ctx is not None and self._queue is not None
        assert self._kernel_hash is not None and self._d_ms is not None

        n = len(nonces)
        t0, t1, t2, _ = header_tail_words(header80)
        if midstate != self._uploaded_ms:
            self._host_ms[:] = struct.unpack("<8I", midstate)
            cl.enqueue_copy(self._queue, self._d_ms, self._host_ms)
            self._uploaded_ms = bytes(midstate)

        host_nonces = np.array([int(x) & 0xFFFFFFFF for x in nonces], dtype=np.uint32)
        host_out = np.zeros(n * 8, dtype=np.uint32)
        mf = cl.mem_flags
        d_nonces = cl.Buffer(self._ctx, mf.READ_ONLY | mf.COPY_HOST_PTR, hostbuf=host_nonces)
        d_dig = cl.Buffer(self._ctx, mf.WRITE_ONLY, host_out.nbytes)

        self._kernel_hash.set_args(
            self._d_ms,
            np.uint32(t0),
            np.uint32(t1),
            np.uint32(t2),
            d_nonces,
            d_dig,
            np.uint32(n),
        )
        local = int(self._local_size)
        global_size = ((n + local - 1) // local) * local
        cl.enqueue_nd_range_kernel(
            self._queue, self._kernel_hash, (global_size,), (local,)
        )
        cl.enqueue_copy(self._queue, host_out, d_dig)
        self._queue.finish()

        digests: list[bytes] = []
        for i in range(n):
            words = host_out[i * 8 : (i + 1) * 8]
            digests.append(struct.pack(">8I", *[int(x) for x in words]))
        return digests


_miner_singleton: Optional[GpuMiner] = None


def get_gpu_miner() -> GpuMiner:
    global _miner_singleton
    if _miner_singleton is None:
        _miner_singleton = GpuMiner()
    return _miner_singleton
