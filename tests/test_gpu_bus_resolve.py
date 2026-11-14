from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from gpu.miner import _nvml_bus_number, _pick_nvidia_gpu  # noqa: E402
from monitor.gpu_devices import GpuDevice, resolve_gpu  # noqa: E402


def test_nvml_bus_number_parses():
    assert _nvml_bus_number("00000000:01:00.0") == 1
    assert _nvml_bus_number("0000:0A:00.0") == 10
    assert _nvml_bus_number("") is None


def test_resolve_gpu_single_auto(monkeypatch):
    devices = [
        GpuDevice(
            index=0,
            name="GPU-A",
            bus_id="00000000:01:00.0",
            uuid="GPU-AAAA",
            total_vram_bytes=8 << 30,
            free_vram_bytes=7 << 30,
        )
    ]
    monkeypatch.setattr("monitor.gpu_devices.list_gpus", lambda: devices)
    d = resolve_gpu()
    assert d.bus_id.endswith("01:00.0")
    assert d.uuid == "GPU-AAAA"


def test_resolve_gpu_multi_requires_selection(monkeypatch):
    devices = [
        GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1),
        GpuDevice(1, "B", "00000000:02:00.0", "GPU-B", 1, 1),
    ]
    monkeypatch.setattr("monitor.gpu_devices.list_gpus", lambda: devices)
    with pytest.raises(RuntimeError, match="Multiple GPUs"):
        resolve_gpu()
    by_bus = resolve_gpu(bus_id="00000000:02:00.0")
    assert by_bus.uuid == "GPU-B"
    by_uuid = resolve_gpu(uuid="GPU-A")
    assert by_uuid.bus_id.endswith("01:00.0")


def test_resolve_gpu_wrong_bus(monkeypatch):
    devices = [GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1)]
    monkeypatch.setattr("monitor.gpu_devices.list_gpus", lambda: devices)
    with pytest.raises(RuntimeError, match="PCI bus mismatch"):
        resolve_gpu(bus_id="00000000:99:00.0")


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
    name = "NVIDIA CUDA"

    def __init__(self, devs):
        self._devs = devs

    def get_devices(self, device_type=None):
        return self._devs


def test_pick_opencl_matches_nvml_bus():
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
    _p, d = _pick_nvidia_gpu(cl, prefer_bus_id="00000000:02:00.0")
    assert d.name == "GeForce B"


def test_pick_opencl_multi_requires_bus():
    from gpu.miner import GpuUnavailableError

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
        _pick_nvidia_gpu(cl, prefer_bus_id=None)


def test_pick_opencl_single_gpu_falls_back_on_pci_mismatch():
    cl = SimpleNamespace(
        get_platforms=lambda: [
            _FakePlat([_FakeDev("GeForce A", "NVIDIA", 1)])
        ],
        device_type=SimpleNamespace(GPU=1),
    )
    _p, d = _pick_nvidia_gpu(cl, prefer_bus_id="00000000:09:00.0")
    assert d.name == "GeForce A"


def test_pick_opencl_multi_rejects_mismatched_bus():
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
    from gpu.miner import GpuUnavailableError

    with pytest.raises(GpuUnavailableError, match="OpenCL PCI bus did not match"):
        _pick_nvidia_gpu(cl, prefer_bus_id="00000000:09:00.0")
