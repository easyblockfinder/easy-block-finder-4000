from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import validate_address_for_network, validate_xmr_address  # noqa: E402
from mining.keccak256 import keccak_256  # noqa: E402

# docs.getmonero.org standard address ornegi
_REF = (
    "4AdUndXHHZ6cfufTMvppY6JwXNouMBzSkbLYfpAV5Usx3skxNgYeYTRj5UzqtReoS44qo9mtmXCqY45DJ852K5Jv2684Rge"
)


def test_fake_all_ones_rejected():
    fake = "4" + ("1" * 94)
    ok, err = validate_xmr_address(fake)
    assert not ok
    assert "checksum" in err.lower() or "base58" in err.lower() or "kec" in err.lower()


def test_reference_mainnet_standard():
    ok, err = validate_xmr_address(_REF)
    assert ok, err
    ok, _ = validate_address_for_network("xmr", _REF)
    assert ok


def test_keccak_not_sha3():
    # Bos Keccak-256 ≠ SHA3-256
    assert keccak_256(b"").hex() == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )


def test_corrupted_checksum():
    # Son karakteri boz
    bad = _REF[:-1] + ("e" if _REF[-1] != "e" else "f")
    ok, err = validate_xmr_address(bad)
    assert not ok


def test_empty_and_short():
    assert validate_xmr_address("")[0] is False
    assert validate_xmr_address("4abc")[0] is False
