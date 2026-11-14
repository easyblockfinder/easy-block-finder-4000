from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from engines.rigel_runner import (  # noqa: E402
    parse_rigel_list_devices,
    resolve_rigel_device_index,
)
from monitor.gpu_devices import GpuDevice  # noqa: E402


SAMPLE = """
Rigel v1.23.2
GPU #0  [0000:01:00.0]  NVIDIA GeForce GTX 1650  4096 MB
GPU #1  [0000:02:00.0]  NVIDIA GeForce RTX 3060  12288 MB
"""


def test_parse_rigel_list_devices():
    devices = parse_rigel_list_devices(SAMPLE)
    assert len(devices) == 2
    assert devices[0]["index"] == 0
    assert "01:00.0" in devices[0]["bus_id"].upper()
    assert devices[1]["index"] == 1


def test_resolve_matches_bus_not_nvml_order():
    # NVML index reandrse; Rigel listesi PCI ordersi
    nvml = [
        GpuDevice(5, "B", "00000000:02:00.0", "GPU-B", 1, 1),
        GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1),
    ]
    idx = resolve_rigel_device_index(
        selected_bus="00000000:02:00.0",
        selected_uuid="GPU-B",
        rigel_devices=parse_rigel_list_devices(SAMPLE),
        nvml_devices=nvml,
    )
    assert idx == 1


def test_cuda_visible_mismatch_raises():
    with pytest.raises(RuntimeError, match="match|could not be verified|CUDA_VISIBLE"):
        resolve_rigel_device_index(
            selected_bus="00000000:09:00.0",
            selected_uuid="",
            rigel_devices=parse_rigel_list_devices(SAMPLE),
            nvml_devices=[
                GpuDevice(0, "A", "00000000:01:00.0", "GPU-A", 1, 1),
            ],
        )
