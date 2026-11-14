"""Pre-start temperature probe — GPU (NVML) or CPU sensors."""

from __future__ import annotations

from typing import Optional


def probe_temperature_readable(
    network_id: str,
    *,
    gpu_bus_id: Optional[str] = None,
    gpu_uuid: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Returns (readable, detail).
    XMR → CPU sensors; BTC/BCH/RVN/ERG → NVML for selected/auto GPU.
    """
    nid = (network_id or "").strip().lower()
    if nid == "xmr":
        from monitor.cpu_temp import CpuTemperatureMonitor

        mon = CpuTemperatureMonitor()
        if mon.available:
            return True, mon.source_name
        return False, f"CPU temperature unreadable ({mon.source_name})"

    from monitor.gpu_devices import resolve_gpu, temperature_for_bus

    nvidia_only = nid in ("rvn", "erg")
    try:
        gpu = resolve_gpu(
            bus_id=(gpu_bus_id or "").strip() or None,
            uuid=(gpu_uuid or "").strip() or None,
            nvidia_only=nvidia_only,
        )
    except RuntimeError as exc:
        return False, f"GPU resolve failed (cannot read temp): {exc}"

    temp, src = temperature_for_bus(gpu.bus_id)
    if temp is not None:
        return True, src or f"NVML bus={gpu.bus_id}"
    return False, src or f"NVML temperature unreadable for bus={gpu.bus_id}"
