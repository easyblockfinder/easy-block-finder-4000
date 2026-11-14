"""Network/engine hardware port — separate from the application startup."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
MARKER = ROOT / ".deps_ok"


def deps_mode() -> str:
    """full | cpu-only | unknown"""
    env = os.environ.get("SOLOBLOCKSTRIKE_CPU_ONLY", "").strip().lower()
    if env in ("1", "true", "yes"):
        return "cpu-only"
    if not MARKER.is_file():
        return "unknown"
    try:
        text = MARKER.read_text(encoding="utf-8").strip().lower()
    except OSError:
        return "unknown"
    if text.startswith("cpu"):
        return "cpu-only"
    if text.startswith("full") or text == "ok":
        return "full"
    return "unknown"


_gpu_cache: Optional[tuple[bool, str]] = None
_nvidia_cache: Optional[tuple[bool, str]] = None


def opencl_gpu_available(*, force: bool = False) -> tuple[bool, str]:
    """Any OpenCL GPU (NVIDIA / AMD / Intel) usable for BTC/BCH."""
    global _gpu_cache
    if _gpu_cache is not None and not force:
        return _gpu_cache
    try:
        from gpu.miner import GpuMiner

        m = GpuMiner(autotune_local=False)
        name = m.device_name or "GPU"
        m.close()
        _gpu_cache = (True, name)
    except Exception as exc:
        _gpu_cache = (False, str(exc))
    return _gpu_cache


def opencl_nvidia_available(*, force: bool = False) -> tuple[bool, str]:
    """
    NVIDIA present for CUDA/Rigel (RVN/ERG) or legacy callers.
    Prefers NVML list; falls back to OpenCL vendor=nvidia.
    """
    global _nvidia_cache
    if _nvidia_cache is not None and not force:
        return _nvidia_cache
    try:
        from monitor.gpu_devices import list_gpus

        nvidia = [d for d in list_gpus() if d.vendor == "nvidia"]
        if nvidia:
            _nvidia_cache = (True, nvidia[0].name)
            return _nvidia_cache
        _nvidia_cache = (False, "No NVIDIA GPU in NVML/OpenCL list")
    except Exception as exc:
        # Fall back to full OpenCL miner probe (NVIDIA-only historically)
        try:
            ok, detail = opencl_gpu_available(force=force)
            if ok and "amd" not in detail.lower() and "intel" not in detail.lower():
                _nvidia_cache = (True, detail)
            else:
                _nvidia_cache = (False, str(exc) if not ok else f"Non-NVIDIA GPU: {detail}")
        except Exception as exc2:
            _nvidia_cache = (False, str(exc2))
    return _nvidia_cache


def network_block_reason(
    network_id: str, *, probe_gpu: bool = False
) -> Optional[str]:
    """
    None = selectable.
    probe_gpu=False: cpu-only marker only (no OpenCL probe at UI startup — no freeze).
    probe_gpu=True: real OpenCL / NVIDIA check before Start.
    """
    nid = (network_id or "").strip().lower()
    if nid == "xmr":
        return None
    mode = deps_mode()
    needs_gpu = nid in ("btc", "bch", "rvn", "erg")
    if not needs_gpu:
        return None
    if mode == "cpu-only":
        return (
            f"{nid.upper()}: this session started CPU-only (no GPU/OpenCL). "
            "Only XMR (CPU) is available. For GPU: start.bat force"
        )
    if not probe_gpu:
        return None

    # RVN/ERG: Rigel is CUDA-only — AMD/Intel not supported in this phase
    if nid in ("rvn", "erg"):
        ok, detail = opencl_nvidia_available()
        if not ok:
            return (
                f"{nid.upper()}: NVIDIA CUDA GPU required (Rigel). "
                f"{detail}. AMD/Intel support for this network is not enabled yet; "
                "use BTC/BCH (OpenCL) or XMR (CPU)."
            )
        return None

    # BTC/BCH: any OpenCL GPU
    ok, detail = opencl_gpu_available()
    if not ok:
        return (
            f"{nid.upper()}: OpenCL GPU required (NVIDIA / AMD / Intel) — {detail}. "
            "You can select XMR with CPU."
        )
    return None
