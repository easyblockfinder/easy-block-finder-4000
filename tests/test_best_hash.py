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
def test_digest_pack_matches_be_words_and_pow_order():
    import struct
    from mining.bitcoin import hash256

    header = bytes.fromhex(
        "0100000000000000000000000000000000000000000000000000000000000000"
        "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
        "4b1e5e4a29ab5f49ffff001d1dac2b7c"
    )
    digest = hash256(header)
    words = struct.unpack(">8I", digest)
    assert struct.pack(">8I", *words) == digest
    # GPU key[0..7] = BSWAP(h7..h0) == display-order big-endian words
    key = [struct.unpack("<I", struct.pack(">I", words[7 - i]))[0] for i in range(8)]
    assert struct.pack(">8I", *key) == digest[::-1]
    assert int.from_bytes(digest, "little") == int.from_bytes(struct.pack(">8I", *key), "big")


def test_pick_best_candidate_hex():
    from mining.best_hash import pick_best_candidate_hex

    lo = "00" * 4 + "11" * 28
    hi = "00" * 3 + "ff" * 29
    assert pick_best_candidate_hex([hi, lo, "zz", ""]) == lo
    assert pick_best_candidate_hex([]) is None
    assert pick_best_candidate_hex(["bad", "00" * 32]) is None


def test_format_diff_short():
    from mining.best_hash import format_diff_short

    assert format_diff_short(None) == "\u2014"
    assert format_diff_short(95.2e12) == "95.2T"
    assert format_diff_short(12_400) == "12.4k"
    assert format_diff_short(3.5) == "3.50"
    assert format_diff_short(1.5e15) == "1.5P"
