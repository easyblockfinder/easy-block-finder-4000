"""Vendor-agnostic GPU enum / OpenCL pick / hardware gate (no real GPU required)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from gpu.miner import GpuUnavailableError, _pick_opencl_gpu  # noqa: E402
from monitor import hardware_gate as hg  # noqa: E402
from monitor.gpu_devices import (  # noqa: E402
    GpuDevice,
    classify_vendor,
    list_gpus,
    resolve_gpu,
)


def test_classify_vendor_nvidia_amd_intel():
    assert classify_vendor("NVIDIA Corporation", "GeForce RTX 3080") == "nvidia"
    assert classify_vendor("Advanced Micro Devices, Inc.", "gfx1030") == "amd"
    assert classify_vendor("AMD", "Radeon RX 6800") == "amd"
    assert classify_vendor("Intel(R) Corporation", "Intel(R) Arc(TM) A770") == "intel"
    assert classify_vendor("Somebody", "WeirdGPU") == "unknown"


class _FakeDev:
    def __init__(self, name: str, vendor: str, pci: int | None):
        self.name = name
        self.vendor = vendor
        self._pci = pci

    def get_info(self, code):
        if self._pci is None:
            raise RuntimeError("no pci")
        return self._pci


class _FakePlat:
    name = "FakeCL"

    def __init__(self, devs):
        self._devs = devs

    def get_devices(self, device_type=None):
        return self._devs


def test_pick_opencl_accepts_amd():
    cl = SimpleNamespace(
        get_platforms=lambda: [
            _FakePlat([_FakeDev("gfx1030", "Advanced Micro Devices, Inc.", 3)])
        ],
        device_type=SimpleNamespace(GPU=1),
    )
    _p, d = _pick_opencl_gpu(cl, prefer_bus_id=None)
    assert "gfx1030" in d.name


def test_pick_opencl_matches_amd_bus():
    cl = SimpleNamespace(
        get_platforms=lambda: [
            _FakePlat(
                [
                    _FakeDev("AMD-A", "AMD", 1),
                    _FakeDev("AMD-B", "AMD", 5),
                ]
            )
        ],
        device_type=SimpleNamespace(GPU=1),
    )
    _p, d = _pick_opencl_gpu(cl, prefer_bus_id="00000000:05:00.0")
    assert d.name == "AMD-B"


def test_pick_opencl_intel_single():
    cl = SimpleNamespace(
        get_platforms=lambda: [
            _FakePlat([_FakeDev("Intel(R) Arc(TM) A750", "Intel(R) Corporation", 8)])
        ],
        device_type=SimpleNamespace(GPU=1),
    )
    _p, d = _pick_opencl_gpu(cl, prefer_bus_id="00000000:08:00.0")
    assert "Arc" in d.name


def test_list_gpus_merges_nvml_and_opencl_amd(monkeypatch):
    nvidia = [
        GpuDevice(
            0,
            "RTX 3060",
            "00000000:01:00.0",
            "GPU-NV",
            8 << 30,
            7 << 30,
            vendor="nvidia",
        )
    ]
    amd = [
        GpuDevice(
            0,
            "RX 6800",
            "00000000:03:00.0",
            "",
            16 << 30,
            15 << 30,
            vendor="amd",
        )
    ]
    monkeypatch.setattr("monitor.gpu_devices.list_nvidia_gpus", lambda: nvidia)
    monkeypatch.setattr("monitor.gpu_devices.list_opencl_gpus", lambda: amd + [
        GpuDevice(
            1,
            "RTX 3060 OpenCL",
            "00000000:01:00.0",
            "",
            8 << 30,
            8 << 30,
            vendor="nvidia",
        )
    ])
    got = list_gpus()
    vendors = {d.vendor for d in got}
    assert vendors == {"nvidia", "amd"}
    assert len(got) == 2  # OpenCL NVIDIA duplicate skipped


def test_resolve_gpu_from_list_gpus(monkeypatch):
    devices = [
        GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1, vendor="amd"),
        GpuDevice(1, "B", "00000000:02:00.0", "GPU-B", 1, 1, vendor="nvidia"),
    ]
    monkeypatch.setattr("monitor.gpu_devices.list_gpus", lambda: devices)
    assert resolve_gpu(bus_id="00000000:01:00.0").vendor == "amd"
    assert resolve_gpu(uuid="GPU-B").vendor == "nvidia"
    with pytest.raises(RuntimeError, match="Multiple GPUs"):
        resolve_gpu()


def test_resolve_nvidia_only_skips_amd(monkeypatch):
    devices = [
        GpuDevice(0, "A", "00000000:01:00.0", "", 1, 1, vendor="amd"),
        GpuDevice(1, "B", "00000000:02:00.0", "GPU-B", 1, 1, vendor="nvidia"),
    ]
    monkeypatch.setattr("monitor.gpu_devices.list_gpus", lambda: devices)
    d = resolve_gpu(nvidia_only=True)
    assert d.vendor == "nvidia"


def test_gate_btc_uses_any_opencl(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    (tmp_path / ".deps_ok").write_text("full\n", encoding="utf-8")
    monkeypatch.delenv("SOLOBLOCKSTRIKE_CPU_ONLY", raising=False)
    hg._gpu_cache = None
    hg._nvidia_cache = None
    monkeypatch.setattr(hg, "opencl_gpu_available", lambda force=False: (True, "RX 6800 [amd]"))
    assert hg.network_block_reason("btc", probe_gpu=True) is None
    assert hg.network_block_reason("bch", probe_gpu=True) is None


def test_gate_rvn_requires_nvidia(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    (tmp_path / ".deps_ok").write_text("full\n", encoding="utf-8")
    monkeypatch.delenv("SOLOBLOCKSTRIKE_CPU_ONLY", raising=False)
    hg._gpu_cache = None
    hg._nvidia_cache = None
    monkeypatch.setattr(
        hg, "opencl_nvidia_available", lambda force=False: (False, "AMD only")
    )
    reason = hg.network_block_reason("rvn", probe_gpu=True)
    assert reason is not None
    assert "NVIDIA" in reason
    assert "AMD/Intel" in reason or "not enabled" in reason


def test_gate_select_page_no_probe(monkeypatch, tmp_path):
    monkeypatch.setattr(hg, "MARKER", tmp_path / ".deps_ok")
    (tmp_path / ".deps_ok").write_text("full\n", encoding="utf-8")
    monkeypatch.delenv("SOLOBLOCKSTRIKE_CPU_ONLY", raising=False)
    called = {"n": 0}

    def boom(**_k):
        called["n"] += 1
        return False, "no"

    monkeypatch.setattr(hg, "opencl_gpu_available", boom)
    monkeypatch.setattr(hg, "opencl_nvidia_available", boom)
    assert hg.network_block_reason("btc", probe_gpu=False) is None
    assert called["n"] == 0


def test_pick_opencl_multi_requires_bus_english():
    cl = SimpleNamespace(
        get_platforms=lambda: [
            _FakePlat(
                [
                    _FakeDev("GeForce A", "NVIDIA", 1),
                    _FakeDev("GeForce B", "NVIDIA", 2),
                ]
            )
        ],
        device_type=SimpleNamespace(GPU=1),
    )
    with pytest.raises(GpuUnavailableError, match="multiple OpenCL GPUs"):
        _pick_opencl_gpu(cl, prefer_bus_id=None)
