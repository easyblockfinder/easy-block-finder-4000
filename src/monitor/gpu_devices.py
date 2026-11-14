"""GPU listesi: NVIDIA (NVML) + AMD/Intel (OpenCL). PCI bus / UUID + VRAM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class GpuDevice:
    index: int
    name: str
    bus_id: str
    uuid: str
    total_vram_bytes: int
    free_vram_bytes: int
    vendor: str = "nvidia"  # nvidia | amd | intel | unknown

    @property
    def total_vram_mb(self) -> int:
        return int(self.total_vram_bytes // (1024 * 1024))

    @property
    def free_vram_mb(self) -> int:
        return int(self.free_vram_bytes // (1024 * 1024))


def classify_vendor(vendor: str, name: str = "") -> str:
    blob = f"{vendor} {name}".lower()
    if "nvidia" in blob:
        return "nvidia"
    # Check Intel before AMD: "Corporation" contains the substring "ati"
    if "intel" in blob:
        return "intel"
    if (
        "advanced micro devices" in blob
        or "radeon" in blob
        or blob.strip().startswith("amd")
        or " amd " in f" {blob} "
        or blob.strip().startswith("ati ")
        or " ati " in f" {blob} "
    ):
        return "amd"
    # Bare vendor token "AMD" / "ATI"
    v = (vendor or "").strip().lower()
    if v in ("amd", "ati"):
        return "amd"
    return "unknown"


def list_nvidia_gpus() -> list[GpuDevice]:
    try:
        import pynvml

        pynvml.nvmlInit()
    except Exception as exc:
        raise RuntimeError(f"NVML init failed: {exc}") from exc

    out: list[GpuDevice] = []
    try:
        count = int(pynvml.nvmlDeviceGetCount())
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            try:
                pci = pynvml.nvmlDeviceGetPciInfo(handle)
                bus = pci.busId if isinstance(pci.busId, str) else pci.busId.decode()
            except Exception:
                bus = f"index:{i}"
            try:
                uuid = pynvml.nvmlDeviceGetUUID(handle)
                if isinstance(uuid, bytes):
                    uuid = uuid.decode("utf-8", errors="replace")
            except Exception:
                uuid = ""
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            out.append(
                GpuDevice(
                    index=i,
                    name=str(name),
                    bus_id=str(bus).strip(),
                    uuid=str(uuid).strip(),
                    total_vram_bytes=int(mem.total),
                    free_vram_bytes=int(mem.free),
                    vendor="nvidia",
                )
            )
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass
    return out


# OpenCL PCI / topology extensions
_CL_DEVICE_PCI_BUS_ID_NV = 0x4008
_CL_DEVICE_TOPOLOGY_AMD = 0x4037
_CL_DEVICE_PCI_BUS_ID_KHR = 0x4251
_CL_DEVICE_PCI_SLOT_ID_KHR = 0x4252
_CL_DEVICE_TOPOLOGY_TYPE_PCIE_AMD = 1


def _opencl_pci_bus_id(device) -> str:
    """Best-effort PCI bus string for OpenCL devices (NVIDIA / AMD / KHR)."""
    # NVIDIA: bus number only → synthesize domain:bus:00.0
    try:
        bus_num = int(device.get_info(_CL_DEVICE_PCI_BUS_ID_NV))
        return f"00000000:{bus_num:02X}:00.0"
    except Exception:
        pass
    # cl_khr_pci_bus_info
    try:
        bus = int(device.get_info(_CL_DEVICE_PCI_BUS_ID_KHR))
        slot = int(device.get_info(_CL_DEVICE_PCI_SLOT_ID_KHR))
        device_id = (slot >> 3) & 0x1F
        function = slot & 0x7
        return f"00000000:{bus:02X}:{device_id:02X}.{function}"
    except Exception:
        pass
    # AMD topology
    try:
        topo = device.get_info(_CL_DEVICE_TOPOLOGY_AMD)
        # pyopencl may return bytes, tuple, or object with .pcie
        bus = device_id = function = None
        if hasattr(topo, "pcie"):
            pcie = topo.pcie
            bus = int(getattr(pcie, "bus", 0))
            device_id = int(getattr(pcie, "device", 0))
            function = int(getattr(pcie, "function", 0))
        elif isinstance(topo, (bytes, bytearray)):
            # raw layout: type u32 + padding; bus at offset 21
            if len(topo) >= 24:
                t = int.from_bytes(topo[0:4], "little")
                if t == _CL_DEVICE_TOPOLOGY_TYPE_PCIE_AMD:
                    bus = topo[21]
                    device_id = topo[22]
                    function = topo[23]
        elif isinstance(topo, (tuple, list)) and len(topo) >= 2:
            # (type, raw...) — best effort
            pass
        if bus is not None and device_id is not None and function is not None:
            return f"00000000:{int(bus):02X}:{int(device_id):02X}.{int(function)}"
    except Exception:
        pass
    return ""


def list_opencl_gpus() -> list[GpuDevice]:
    """Enumerate OpenCL GPUs (NVIDIA / AMD / Intel) without creating a miner context."""
    try:
        import pyopencl as cl
    except ImportError as exc:
        raise RuntimeError(f"pyopencl not installed: {exc}") from exc

    try:
        platforms = cl.get_platforms()
    except Exception as exc:
        raise RuntimeError(f"OpenCL platforms unavailable: {exc}") from exc

    out: list[GpuDevice] = []
    idx = 0
    for p in platforms:
        try:
            devs = p.get_devices(device_type=cl.device_type.GPU)
        except Exception:
            continue
        for d in devs:
            vendor_raw = getattr(d, "vendor", "") or ""
            name = (getattr(d, "name", "") or "").strip() or "OpenCL GPU"
            vendor = classify_vendor(vendor_raw, name)
            bus = _opencl_pci_bus_id(d)
            try:
                total = int(d.global_mem_size)
            except Exception:
                total = 0
            out.append(
                GpuDevice(
                    index=idx,
                    name=name,
                    bus_id=bus or f"opencl:{idx}",
                    uuid="",
                    total_vram_bytes=total,
                    free_vram_bytes=total,
                    vendor=vendor,
                )
            )
            idx += 1
    return out


def _device_merge_key(d: GpuDevice) -> str:
    if d.uuid:
        return f"uuid:{d.uuid.strip().upper()}"
    bus = (d.bus_id or "").strip().upper()
    if bus and not bus.startswith("OPENCL:") and not bus.startswith("INDEX:"):
        # Normalize bus number for NV vs OpenCL synthetic IDs
        return f"bus:{bus}"
    return f"name:{d.vendor}:{d.name.strip().upper()}"


def list_gpus() -> list[GpuDevice]:
    """
    All discrete GPUs: prefer NVML for NVIDIA; add AMD/Intel (and NVIDIA if NVML fails)
    via OpenCL enumeration.
    """
    merged: dict[str, GpuDevice] = {}
    nvml_error: Optional[Exception] = None

    try:
        for d in list_nvidia_gpus():
            merged[_device_merge_key(d)] = d
    except Exception as exc:
        nvml_error = exc

    try:
        for d in list_opencl_gpus():
            if d.vendor == "nvidia" and any(
                x.vendor == "nvidia" for x in merged.values()
            ):
                # Prefer richer NVML records; skip OpenCL NVIDIA duplicates
                continue
            key = _device_merge_key(d)
            if key not in merged:
                merged[key] = d
    except Exception:
        if not merged and nvml_error is not None:
            raise RuntimeError(
                f"No GPUs found (NVML: {nvml_error})"
            ) from nvml_error
        if not merged:
            raise

    if not merged:
        if nvml_error is not None:
            raise RuntimeError(f"No GPUs found (NVML: {nvml_error})") from nvml_error
        raise RuntimeError("No GPUs found.")

    # Re-index stably by PCI bus then name
    ordered = sorted(
        merged.values(),
        key=lambda d: (_bus_sort_key(d.bus_id), d.name.lower()),
    )
    return [
        GpuDevice(
            index=i,
            name=d.name,
            bus_id=d.bus_id,
            uuid=d.uuid,
            total_vram_bytes=d.total_vram_bytes,
            free_vram_bytes=d.free_vram_bytes,
            vendor=d.vendor,
        )
        for i, d in enumerate(ordered)
    ]


def list_nvidia_only() -> list[GpuDevice]:
    """NVIDIA devices only (Rigel / CUDA path)."""
    return [d for d in list_gpus() if d.vendor == "nvidia"]


def resolve_gpu(
    *,
    bus_id: Optional[str] = None,
    uuid: Optional[str] = None,
    nvidia_only: bool = False,
) -> GpuDevice:
    devices = list_nvidia_only() if nvidia_only else list_gpus()
    if not devices:
        raise RuntimeError("No GPU found.")
    if uuid:
        for d in devices:
            if d.uuid == uuid:
                return d
        raise RuntimeError(f"UUID mismatch: {uuid}")
    if bus_id:
        want = bus_id.strip().upper()
        for d in devices:
            if d.bus_id.strip().upper() == want:
                return d
        # Match by bus number only (NVML full vs OpenCL synthetic)
        want_num = _bus_number(want)
        if want_num is not None:
            for d in devices:
                if _bus_number(d.bus_id) == want_num:
                    return d
        raise RuntimeError(f"PCI bus mismatch: {bus_id}")
    if len(devices) == 1:
        return devices[0]
    raise RuntimeError(
        "Multiple GPUs; set gpu_bus_id or gpu_uuid "
        "(OpenCL/NVML index equality is not sufficient)."
    )


def _bus_number(bus_id: str) -> Optional[int]:
    text = (bus_id or "").strip().upper()
    if not text or text.startswith("OPENCL:") or text.startswith("INDEX:"):
        return None
    try:
        parts = text.replace(".", ":").split(":")
        if len(parts) >= 2:
            return int(parts[1], 16)
    except ValueError:
        pass
    return None


def temperature_for_bus(bus_id: str) -> tuple[Optional[int], str]:
    """NVML temperature for the same bus ID; returns the source tag."""
    try:
        import pynvml

        pynvml.nvmlInit()
        count = int(pynvml.nvmlDeviceGetCount())
        want = bus_id.strip().upper()
        want_num = _bus_number(want)
        for i in range(count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            pci = pynvml.nvmlDeviceGetPciInfo(handle)
            bus = pci.busId if isinstance(pci.busId, str) else pci.busId.decode()
            bus_s = str(bus).strip().upper()
            if bus_s != want and not (
                want_num is not None and _bus_number(bus_s) == want_num
            ):
                continue
            temp = int(
                pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            )
            src = f"NVML bus={bus} index={i}"
            pynvml.nvmlShutdown()
            return temp, src
        pynvml.nvmlShutdown()
        return None, f"NVML bus not found: {bus_id}"
    except Exception as exc:
        return None, f"NVML error: {exc}"


def _bus_sort_key(bus_id: str) -> tuple:
    """PCI bus order (same as Rigel --list-devices: PCI bus ascending)."""
    text = (bus_id or "").strip().upper().replace(".", ":")
    parts = text.split(":")
    nums: list[int] = []
    for p in parts:
        try:
            nums.append(int(p, 16))
        except ValueError:
            nums.append(0)
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])


def devices_ordered_by_pci_bus(devices: Optional[list[GpuDevice]] = None) -> list[GpuDevice]:
    """Rigel device index = Position in the list sorted by PCI bus (not NVML index)."""
    devs = list(devices) if devices is not None else list_nvidia_gpus()
    return sorted(devs, key=lambda d: _bus_sort_key(d.bus_id))


def rigel_device_index_for(
    *,
    bus_id: Optional[str] = None,
    uuid: Optional[str] = None,
    devices: Optional[list[GpuDevice]] = None,
) -> tuple[int, GpuDevice]:
    """
    Rigel -d index for the selected physical GPU.
    NVML index is not assumed to match Rigel/CUDA; PCI bus order is used.
    """
    ordered = devices_ordered_by_pci_bus(devices)
    if not ordered:
        raise RuntimeError("No NVIDIA GPU found.")
    selected = (
        resolve_gpu(bus_id=bus_id, uuid=uuid, nvidia_only=True)
        if devices is None
        else None
    )
    if devices is not None:
        if uuid:
            matches = [d for d in ordered if d.uuid == uuid]
        elif bus_id:
            want = bus_id.strip().upper()
            matches = [d for d in ordered if d.bus_id.strip().upper() == want]
            if not matches:
                want_num = _bus_number(want)
                if want_num is not None:
                    matches = [
                        d for d in ordered if _bus_number(d.bus_id) == want_num
                    ]
        else:
            if len(ordered) != 1:
                raise RuntimeError("Multiple GPUs: bus/UUID required.")
            matches = [ordered[0]]
        if not matches:
            raise RuntimeError("Selected GPU not in PCI list.")
        selected = matches[0]
    assert selected is not None
    for i, d in enumerate(ordered):
        if d.bus_id.strip().upper() == selected.bus_id.strip().upper() and (
            not selected.uuid or d.uuid == selected.uuid or not d.uuid
        ):
            return i, d
        if selected.uuid and d.uuid == selected.uuid:
            return i, d
    raise RuntimeError(
        f"Rigel PCI mapping failed (bus={selected.bus_id} uuid={selected.uuid}). "
        "Will not silently pick another card."
    )
