"""Kesirli / invalid zorluk → share hedefi."""

from __future__ import annotations

import sys
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from mining.bitcoin import DIFF1_TARGET, share_target_from_difficulty  # noqa: E402


def test_difficulty_one_is_diff1():
    assert share_target_from_difficulty(1) == DIFF1_TARGET
    assert share_target_from_difficulty(1.0) == DIFF1_TARGET


def test_fractional_above_one_not_truncated_to_int():
    """Eski error: int(1.5)==1 → DIFF1; correct: floor(DIFF1 * 2 / 3)."""
    got = share_target_from_difficulty(1.5)
    frac = Fraction("1.5")
    expected = (DIFF1_TARGET * frac.denominator) // frac.numerator
    assert got == expected
    assert got != DIFF1_TARGET  # truncation olsaydi esit olurdu
    assert got == (DIFF1_TARGET * 2) // 3


def test_fractional_below_one():
    got = share_target_from_difficulty(0.5)
    assert got == DIFF1_TARGET * 2


def test_difficulty_two_halves():
    assert share_target_from_difficulty(2.0) == DIFF1_TARGET // 2


@pytest.mark.parametrize("bad", [0, 0.0, -1, -0.01, float("nan"), float("inf"), float("-inf")])
def test_invalid_difficulty_rejected(bad):
    with pytest.raises(ValueError):
        share_target_from_difficulty(bad)


def test_decimal_input():
    assert share_target_from_difficulty(Decimal("1.5")) == share_target_from_difficulty(1.5)
