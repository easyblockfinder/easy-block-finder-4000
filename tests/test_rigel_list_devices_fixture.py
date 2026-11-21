from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engines.rigel_runner import (  # noqa: E402
    _bus_key,
    parse_rigel_list_devices,
    resolve_rigel_device_index,
)

FIX = (ROOT / "tests" / "fixtures" / "rigel_1_23_2_list_devices.txt").read_text(
    encoding="utf-8"
)


def test_parse_real_format_fixture_keeps_domain():
    devices = parse_rigel_list_devices(FIX)
    assert len(devices) == 3
    assert devices[0]["bus_id"].upper().startswith("0000:")
    assert devices[2]["bus_id"].startswith("0001:")


def test_domain_distinguishes_same_bus_dev():
    """domain atilirsa 0000:03 vs 0001:03 would confuse — thisrada different domain."""
    devices = parse_rigel_list_devices(FIX)
    # Ayni thiss:dev.fn different domain
    k0 = _bus_key("0000:03:00.0")
    k1 = _bus_key("0001:03:00.0")
    assert k0 != k1
    idx = resolve_rigel_device_index(
        selected_bus="0001:03:00.0",
        rigel_devices=devices,
    )
    assert idx == 2


def test_ambiguous_domain_raises():
    with pytest.raises(RuntimeError, match=r"ambiguous/missing domain"):
        resolve_rigel_device_index(
            selected_bus="03:00.0",
            rigel_devices=parse_rigel_list_devices(FIX),
        )
