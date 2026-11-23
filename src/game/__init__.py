"""Scratch Mining Game Mode — interactive tile → real SHA256d path."""

from game.scratch_session import (
    BoardIdentity,
    ScratchSession,
    TileResult,
    TileState,
)
from game.tile_space import (
    NONCE_SPACE,
    TILE_COUNT,
    TILE_GRID,
    TILE_NONCE_COUNT,
    tile_nonce_range,
)

__all__ = [
    "BoardIdentity",
    "NONCE_SPACE",
    "ScratchSession",
    "TILE_COUNT",
    "TILE_GRID",
    "TILE_NONCE_COUNT",
    "TileResult",
    "TileState",
    "tile_nonce_range",
]
