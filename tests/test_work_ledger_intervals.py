"""Nonce interval overlap math for Stratum Work Ledger."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from audit.work_ledger import overlap_len, merge_coverage_unique  # noqa: E402


def test_no_overlap():
    assert overlap_len(0, 100, 100, 200) == 0
    assert overlap_len(50, 100, 0, 50) == 0


def test_partial_overlap():
    assert overlap_len(0, 100, 50, 150) == 50
    assert overlap_len(50, 150, 0, 100) == 50


def test_full_containment():
    assert overlap_len(0, 1000, 100, 200) == 100
    assert overlap_len(100, 200, 0, 1000) == 100


def test_identical_range():
    assert overlap_len(0, 8000, 0, 8000) == 8000


def test_merge_coverage_unique():
    # [0,100) + [50,150) → unique 150, dup 50
    u, d = merge_coverage_unique([(0, 100), (50, 150)])
    assert u == 150
    assert d == 50


def test_merge_disjoint():
    u, d = merge_coverage_unique([(0, 100), (200, 300)])
    assert u == 200
    assert d == 0
