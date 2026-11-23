"""Virtual mega-map: every extranonce2 board is a TILE_GRID×TILE_GRID island.

Layout: one vertical shaft (board_col always 0). Left/right stays inside the
same EN2 island (local columns); panning down moves to deeper EN2 boards —
digging deeper. World coordinates are in tile units; only the viewport is
ever materialized.
"""

from __future__ import annotations

from game.tile_space import TILE_COUNT, TILE_GRID


def en2_limit(extranonce2_size: int) -> int:
    return 1 << (8 * max(1, int(extranonce2_size)))


def boards_wide(_extranonce2_size: int) -> int:
    return 1


def boards_tall(extranonce2_size: int) -> int:
    return en2_limit(extranonce2_size)


def board_grid_side(extranonce2_size: int) -> int:
    """Depth of the board shaft (compat name used by UI labels)."""
    return boards_tall(extranonce2_size)


def world_size_tiles(extranonce2_size: int) -> tuple[int, int]:
    """Return (width, height) of the mega-map in tile units."""
    return TILE_GRID, boards_tall(extranonce2_size) * TILE_GRID


def en2_to_board_rc(en2: int, *, extranonce2_size: int) -> tuple[int, int]:
    """Return (board_row, board_col). Vertical shaft → col always 0."""
    limit = en2_limit(extranonce2_size)
    row = int(en2) % limit
    return row, 0


def board_rc_to_en2(row: int, col: int, *, extranonce2_size: int) -> int:
    limit = en2_limit(extranonce2_size)
    return int(row) % limit


def world_xy_to_en2_tile(
    wx: int, wy: int, *, extranonce2_size: int
) -> tuple[int, int] | None:
    """Map world tile coords → (extranonce2, local tile_id)."""
    world_w, world_h = world_size_tiles(extranonce2_size)
    if wx < 0 or wy < 0 or wx >= world_w or wy >= world_h:
        return None
    local_col = int(wx)
    board_row, local_row = divmod(int(wy), TILE_GRID)
    if local_row >= TILE_GRID or local_col >= TILE_GRID:
        return None
    en2 = board_rc_to_en2(board_row, 0, extranonce2_size=extranonce2_size)
    tile_id = local_row * TILE_GRID + local_col
    if tile_id < 0 or tile_id >= TILE_COUNT:
        return None
    return en2, tile_id


def en2_tile_to_world_xy(
    en2: int, tile_id: int, *, extranonce2_size: int
) -> tuple[int, int]:
    row, _col = en2_to_board_rc(en2, extranonce2_size=extranonce2_size)
    tid = int(tile_id) % TILE_COUNT
    local_row, local_col = divmod(tid, TILE_GRID)
    return local_col, row * TILE_GRID + local_row


def state_key(en2: int, tile_id: int) -> int:
    """Compact key: high bits EN2, low 12 bits tile (tile_id < TILE_COUNT ≤ 4096)."""
    return (int(en2) << 12) | (int(tile_id) & 0xFFF)
