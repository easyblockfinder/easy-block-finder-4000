from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from game.mega_map import (  # noqa: E402
    board_grid_side,
    en2_tile_to_world_xy,
    state_key,
    world_size_tiles,
    world_xy_to_en2_tile,
)
from game.tile_space import TILE_GRID  # noqa: E402


def test_en2_size_4_vertical_shaft():
    assert board_grid_side(4) == 1 << 32
    w, h = world_size_tiles(4)
    assert w == TILE_GRID
    assert h == (1 << 32) * TILE_GRID


def test_roundtrip_world_coords_all_local_rows():
    """Every local row inside an island must round-trip (not only row 0)."""
    for tid in (0, 1, TILE_GRID, TILE_GRID + 5, TILE_GRID * TILE_GRID - 1):
        for en2 in (0, 1, 99):
            wx, wy = en2_tile_to_world_xy(en2, tid, extranonce2_size=4)
            assert 0 <= wx < TILE_GRID
            back = world_xy_to_en2_tile(wx, wy, extranonce2_size=4)
            assert back == (en2, tid)


def test_horizontal_neighbors_same_en2():
    """Moving one tile right stays on the same EN2 (vertical shaft)."""
    a = world_xy_to_en2_tile(0, 3, extranonce2_size=4)
    b = world_xy_to_en2_tile(1, 3, extranonce2_size=4)
    assert a is not None and b is not None
    assert a[0] == b[0] == 0
    assert a[1] == 3 * TILE_GRID
    assert b[1] == 3 * TILE_GRID + 1


def test_deeper_board_is_next_en2():
    """Crossing the island height boundary digs into the next EN2."""
    top = world_xy_to_en2_tile(0, TILE_GRID - 1, extranonce2_size=4)
    deeper = world_xy_to_en2_tile(0, TILE_GRID, extranonce2_size=4)
    assert top == (0, (TILE_GRID - 1) * TILE_GRID)
    assert deeper == (1, 0)


def test_state_key_unique():
    assert state_key(0, 1) != state_key(1, 0)
    assert state_key(5, 100) == ((5 << 12) | 100)
