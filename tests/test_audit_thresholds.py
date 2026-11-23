"""DIFF1-based audit threshold targets."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.thresholds import (  # noqa: E402
    AUDIT_DIFFICULTY_THRESHOLDS,
    audit_target_words_flat,
    targets_for_thresholds,
)
from mining.bitcoin import DIFF1_TARGET, share_target_from_difficulty  # noqa: E402


def test_threshold_count_and_monotonic_targets():
    assert len(AUDIT_DIFFICULTY_THRESHOLDS) == 12
    tgts = targets_for_thresholds()
    assert tgts[0] == share_target_from_difficulty(0.001)
    # Higher difficulty → smaller target
    for a, b in zip(tgts, tgts[1:]):
        assert a >= b
    assert tgts[3] == DIFF1_TARGET  # difficulty 1
    assert 4200.0 in AUDIT_DIFFICULTY_THRESHOLDS
    assert 5000.0 in AUDIT_DIFFICULTY_THRESHOLDS
    assert 10000.0 in AUDIT_DIFFICULTY_THRESHOLDS


def test_flat_words_length():
    flat = audit_target_words_flat()
    assert len(flat) == 96
    assert all(isinstance(x, int) and 0 <= x <= 0xFFFFFFFF for x in flat)
