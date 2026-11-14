"""CPU / GPU detection + per-network capability (incl. VRAM gates)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from monitor.hardware_gate import (
    deps_mode,
    opencl_gpu_available,
    opencl_nvidia_available,
)


@dataclass
class DeviceLine:
    name: str
    detail: str = ""


@dataclass
class HardwareReport:
    cpu_ok: bool
    cpu_label: str
    cpu_detail: str
    opencl_ok: bool
    opencl_detail: str
    nvidia_ok: bool
    nvidia_detail: str
    opencl_devices: list[DeviceLine] = field(default_factory=list)
    nvidia_devices: list[DeviceLine] = field(default_factory=list)
    deps_mode: str = "unknown"
    # network_id -> block reason (None = allowed)
    network_blocks: dict[str, Optional[str]] = field(default_factory=dict)
    network_notes: dict[str, str] = field(default_factory=dict)


def _cpu_info() -> tuple[bool, str, str]:
    n = os.cpu_count() or 0
    if n <= 0:
        return False, "CPU", "Could not read CPU count"
    label = f"{n} logical processor(s)"
    detail = "Detected — available for Monero (XMR / XMRig RandomX)"
    # Best-effort friendly name on Windows
    try:
        import platform

        proc = platform.processor() or ""
        if proc.strip():
            label = f"{proc.strip()} · {n} threads"
    except Exception:
        pass
    return True, label, detail


def _list_device_lines(*, nvidia_only: bool = False) -> list[DeviceLine]:
    out: list[DeviceLine] = []
    try:
        from monitor.gpu_devices import list_gpus, list_nvidia_only

        devices = list_nvidia_only() if nvidia_only else list_gpus()
        for d in devices:
            out.append(
                DeviceLine(
                    name=d.name,
                    detail=(
                        f"vendor={d.vendor}  bus={d.bus_id or '—'}  "
                        f"VRAM {d.free_vram_mb}/{d.total_vram_mb} MB free/total"
                    ),
                )
            )
    except Exception as exc:
        out.append(DeviceLine(name="(enumeration failed)", detail=str(exc)))
    return out


def _best_nvidia_vram() -> tuple[int, int, str]:
    """Returns (free_bytes, total_bytes, name) for the GPU with most free VRAM."""
    from monitor.gpu_devices import list_nvidia_only

    devices = list_nvidia_only()
    if not devices:
        return 0, 0, ""
    best = max(devices, key=lambda d: d.free_vram_bytes)
    return best.free_vram_bytes, best.total_vram_bytes, best.name


def _best_opencl_vram() -> tuple[int, int, str]:
    from monitor.gpu_devices import list_gpus

    devices = list_gpus()
    if not devices:
        return 0, 0, ""
    best = max(devices, key=lambda d: d.total_vram_bytes or d.free_vram_bytes)
    return best.free_vram_bytes, best.total_vram_bytes, best.name


def probe_network_capacity(*, include_vram: bool = True) -> dict[str, Optional[str]]:
    """
    Map network_id -> block reason or None if OK.
    Heavy: may query pool height APIs for RVN/ERG DAG estimates.
    """
    from networks.profiles import NETWORK_ORDER

    blocks: dict[str, Optional[str]] = {nid: None for nid in NETWORK_ORDER}
    mode = deps_mode()

    cpu_ok, _, _ = _cpu_info()
    if not cpu_ok:
        blocks["xmr"] = "CPU not detected — Monero (XMRig) cannot run."
    else:
        blocks["xmr"] = None

    if mode == "cpu-only":
        for nid in ("btc", "bch", "rvn", "erg"):
            blocks[nid] = (
                f"{nid.upper()}: session is CPU-only (no GPU/OpenCL stack). "
                "Only XMR is available. Re-run start.bat without cpu-only for GPU."
            )
        return blocks

    opencl_ok, opencl_detail = opencl_gpu_available(force=True)
    nvidia_ok, nvidia_detail = opencl_nvidia_available(force=True)

    for nid in ("btc", "bch"):
        if not opencl_ok:
            blocks[nid] = (
                f"{nid.upper()}: no OpenCL GPU detected — {opencl_detail}. "
                "BTC/BCH need a GPU with OpenCL (NVIDIA / AMD / Intel)."
            )
        elif include_vram:
            free_b, total_b, name = _best_opencl_vram()
            # SHA-256d is light on VRAM; still refuse tiny / unknown adapters
            min_mb = 256
            total_mb = total_b // (1024 * 1024) if total_b else free_b // (1024 * 1024)
            if total_mb and total_mb < min_mb:
                blocks[nid] = (
                    f"{nid.upper()}: GPU '{name}' reports only ~{total_mb} MB VRAM "
                    f"(need at least ~{min_mb} MB for a stable OpenCL path)."
                )
            else:
                blocks[nid] = None
        else:
            blocks[nid] = None

    for nid in ("rvn", "erg"):
        if not nvidia_ok:
            blocks[nid] = (
                f"{nid.upper()}: NVIDIA CUDA GPU required (Rigel) — {nvidia_detail}. "
                "AMD/Intel are not supported for this network in v1.0."
            )
            continue
        if not include_vram:
            blocks[nid] = None
            continue
        free_b, total_b, name = _best_nvidia_vram()
        if free_b <= 0 and total_b <= 0:
            blocks[nid] = (
                f"{nid.upper()}: NVIDIA GPU found but VRAM could not be read ({name or 'unknown'})."
            )
            continue
        try:
            from engines.dag_gate import check_autolykos_vram, check_kawpow_vram

            if nid == "rvn":
                gate = check_kawpow_vram(
                    free_vram_bytes=free_b, total_vram_bytes=total_b or free_b
                )
            else:
                gate = check_autolykos_vram(
                    free_vram_bytes=free_b, total_vram_bytes=total_b or free_b
                )
            if not gate.ok:
                need_mb = max(0, gate.required_bytes // (1024 * 1024))
                free_mb = max(0, free_b // (1024 * 1024))
                blocks[nid] = (
                    f"{nid.upper()} disabled — insufficient free VRAM on '{name}' "
                    f"(free {free_mb} MB, need ~{need_mb} MB)."
                )
            else:
                blocks[nid] = None
        except Exception as exc:
            blocks[nid] = (
                f"{nid.upper()}: could not verify DAG/dataset VRAM requirement — {exc}. "
                "Disabled until the check succeeds (close other GPU apps and retry)."
            )

    return blocks


def build_hardware_report(*, include_vram: bool = False) -> HardwareReport:
    cpu_ok, cpu_label, cpu_detail = _cpu_info()
    opencl_ok, opencl_detail = opencl_gpu_available(force=True)
    nvidia_ok, nvidia_detail = opencl_nvidia_available(force=True)
    report = HardwareReport(
        cpu_ok=cpu_ok,
        cpu_label=cpu_label,
        cpu_detail=cpu_detail,
        opencl_ok=opencl_ok,
        opencl_detail=opencl_detail if opencl_ok else f"Not detected — {opencl_detail}",
        opencl_devices=_list_device_lines(nvidia_only=False) if opencl_ok else [],
        nvidia_ok=nvidia_ok,
        nvidia_detail=nvidia_detail if nvidia_ok else f"Not detected — {nvidia_detail}",
        nvidia_devices=_list_device_lines(nvidia_only=True) if nvidia_ok else [],
        deps_mode=deps_mode(),
    )
    # Detection-only blocks (no DAG height fetch) for the first page summary
    report.network_blocks = probe_network_capacity(include_vram=include_vram)
    for nid, reason in report.network_blocks.items():
        if reason:
            report.network_notes[nid] = reason
        elif nid == "xmr":
            report.network_notes[nid] = "CPU path OK"
        elif nid in ("btc", "bch"):
            report.network_notes[nid] = "OpenCL GPU OK"
        else:
            report.network_notes[nid] = (
                "NVIDIA present — VRAM capacity checked on next screen"
                if not include_vram
                else "NVIDIA + VRAM OK"
            )
    return report
