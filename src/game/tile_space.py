"""Deterministic 32×32 tile → physical nonce range mapping (full 2³², no overlap).

Each tile covers 4× the previous 64×64 design (~4.19M hashes) so the mega-map
has fewer cells and pans/scratches more smoothly.
"""

from __future__ import annotations

TILE_GRID = 32
TILE_COUNT = TILE_GRID * TILE_GRID  # 1024
NONCE_SPACE = 1 << 32  # 4_294_967_296
TILE_NONCE_COUNT = NONCE_SPACE // TILE_COUNT  # 4_194_304

# Default GPU micro-batch inside a tile (interruptible Stop / thermal / job).
GAME_GPU_CHUNK = 262_144


def tile_nonce_range(tile_id: int) -> tuple[int, int]:
    """
    Return [start, end) physical nonce range for tile_id.
    Uses uint64-safe arithmetic; covers [0, 2³²) without overlap or gaps.
    """
    tid = int(tile_id)
    if tid < 0 or tid >= TILE_COUNT:
        raise ValueError(f"tile_id out of range: {tid}")
    start = tid * TILE_NONCE_COUNT
    end = start + TILE_NONCE_COUNT
    if start < 0 or end > NONCE_SPACE or end <= start:
        raise OverflowError(f"invalid tile range tile={tid} [{start},{end})")
    return start, end


def tile_id_for_nonce(nonce: int) -> int:
    n = int(nonce) & 0xFFFFFFFF
    return n // TILE_NONCE_COUNT


def assert_full_coverage() -> None:
    """Sanity: every nonce in exactly one tile."""
    seen_end = 0
    for tid in range(TILE_COUNT):
        start, end = tile_nonce_range(tid)
        if start != seen_end:
            raise AssertionError(f"gap/overlap before tile {tid}")
        seen_end = end
    if seen_end != NONCE_SPACE:
        raise AssertionError(f"coverage end {seen_end} != {NONCE_SPACE}")
