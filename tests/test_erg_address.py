from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import validate_address_for_network, validate_erg_address  # noqa: E402

# Bilinen example mainnet P2PK (documentation)
SAMPLE = "9fRAWhdxEsTcdb8PhGNrZfwqa65zfkuYHAMmkQLcic1gdLSV5vA"


def test_erg_sample_checksum():
    ok, err = validate_erg_address(SAMPLE)
    assert ok, err
    ok, _ = validate_address_for_network("erg", SAMPLE)
    assert ok


def test_erg_rejects_garbage():
    ok, _ = validate_erg_address("9" + ("1" * 50))
    assert not ok
    ok, _ = validate_erg_address("bc1qtest")
    assert not ok
