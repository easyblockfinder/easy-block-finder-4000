from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from monitor.gpu_devices import GpuDevice, rigel_device_index_for  # noqa: E402


def test_rigel_index_follows_pci_order_not_nvml_index():
    # NVML index ters; Rigel PCI ascending → bus 01 = d=0, bus 02 = d=1
    devices = [
        GpuDevice(1, "B", "00000000:02:00.0", "GPU-B", 1, 1),
        GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1),
    ]
    d_idx, d = rigel_device_index_for(bus_id="00000000:02:00.0", devices=devices)
    assert d_idx == 1
    assert d.uuid == "GPU-B"
    d0, a = rigel_device_index_for(uuid="GPU-A", devices=devices)
    assert d0 == 0 and a.uuid == "GPU-A"


def test_rigel_mismatch_raises():
    devices = [GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1)]
    with pytest.raises(RuntimeError):
        rigel_device_index_for(bus_id="00000000:09:00.0", devices=devices)
