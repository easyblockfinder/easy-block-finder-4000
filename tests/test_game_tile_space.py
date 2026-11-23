from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from game.tile_space import (  # noqa: E402
    NONCE_SPACE,
    TILE_COUNT,
    TILE_GRID,
    TILE_NONCE_COUNT,
    assert_full_coverage,
    tile_id_for_nonce,
    tile_nonce_range,
)


def test_tile_count_and_size():
    assert TILE_GRID == 32
    assert TILE_COUNT == 1024
    assert TILE_NONCE_COUNT == 4_194_304
    assert TILE_COUNT * TILE_NONCE_COUNT == NONCE_SPACE


def test_tile_ranges_no_overlap_full_coverage():
    assert_full_coverage()
    s0, e0 = tile_nonce_range(0)
    assert (s0, e0) == (0, 4_194_304)
    s1, e1 = tile_nonce_range(1)
    assert (s1, e1) == (4_194_304, 8_388_608)
    sl, el = tile_nonce_range(TILE_COUNT - 1)
    assert el == NONCE_SPACE
    assert sl == NONCE_SPACE - TILE_NONCE_COUNT


def test_tile_id_for_nonce_roundtrip():
    for tid in (0, 1, 100, TILE_COUNT - 1):
        start, end = tile_nonce_range(tid)
        assert tile_id_for_nonce(start) == tid
        assert tile_id_for_nonce(end - 1) == tid


def test_invalid_tile_raises():
    try:
        tile_nonce_range(-1)
        assert False
    except ValueError:
        pass
    try:
        tile_nonce_range(TILE_COUNT)
        assert False
    except ValueError:
        pass
