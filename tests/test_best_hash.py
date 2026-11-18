from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import DIFF1_TARGET
from mining.best_hash import (
    difficulty_from_hash_int,
    hash_be_hex_to_int,
    is_better_hash,
    network_difficulty_from_nbits,
)


def test_diff1_hash_has_difficulty_one():
    assert difficulty_from_hash_int(DIFF1_TARGET) == pytest.approx(1.0)


def test_smaller_hash_is_better():
    assert is_better_hash(100, 200) is True
    assert is_better_hash(200, 100) is False
    assert is_better_hash(100, None) is True


def test_hash_be_hex_roundtrip_int():
    h = "00000000" + "ff" * 28
    assert hash_be_hex_to_int(h) == int(h, 16)


def test_network_difficulty_genesis_bits():
    # Bitcoin genesis compact bits 0x1d00ffff → difficulty 1
    assert network_difficulty_from_nbits("1d00ffff") == pytest.approx(1.0)