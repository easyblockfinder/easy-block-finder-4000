"""DIFF1-based 256-bit targets for audit difficulty thresholds (no float compare on GPU)."""

from __future__ import annotations

import struct
from typing import Sequence

from mining.bitcoin import DIFF1_TARGET, share_target_from_difficulty

# Cumulative difficulty thresholds (hash meets D iff hash_int <= DIFF1/D).
AUDIT_DIFFICULTY_THRESHOLDS: tuple[float, ...] = (
    0.001,
    0.01,
    0.1,
    1.0,
    10.0,
    100.0,
    1000.0,
    4200.0,
    5000.0,
    10000.0,
    100000.0,
    1000000.0,
)

assert len(AUDIT_DIFFICULTY_THRESHOLDS) == 12


def targets_for_thresholds(
    thresholds: Sequence[float] = AUDIT_DIFFICULTY_THRESHOLDS,
) -> list[int]:
    return [share_target_from_difficulty(d) for d in thresholds]


def target_to_le_words(target: int) -> list[int]:
    return list(struct.unpack("<8I", int(target).to_bytes(32, "little")))


def audit_target_words_flat(
    thresholds: Sequence[float] = AUDIT_DIFFICULTY_THRESHOLDS,
) -> list[int]:
    """12 * 8 little-endian uint32 words for OpenCL audit_targets buffer."""
    flat: list[int] = []
    for t in targets_for_thresholds(thresholds):
        if t > DIFF1_TARGET * 1_000_000:
            # sanity: still must fit 256-bit
            pass
        flat.extend(target_to_le_words(t))
    if len(flat) != 12 * 8:
        raise RuntimeError("audit target flat size mismatch")
    return flat


def hash_digest_meets_target(digest_le_bytes: bytes, target: int) -> bool:
    """digest = raw SHA-256d bytes; Bitcoin PoW int = little-endian interpret."""
    if len(digest_le_bytes) != 32:
        raise ValueError("digest must be 32 bytes")
    return int.from_bytes(digest_le_bytes, "little") <= int(target)
