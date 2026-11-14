"""Hiz gostergesi: batch baslangic→end span’i (yanlis 2× inflation none)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.hashrate import rate_from_window, rate_kernel_only  # noqa: E402


def test_two_batches_one_mhs_each_second():
    # 0–1s: 1e6, 1–2s: 1e6 → real 1e6 H/s (old errorli account 2e6 gosterirdi)
    window = [(0.0, 1.0, 1_000_000), (1.0, 2.0, 1_000_000)]
    assert rate_from_window(window) == pytest.approx(1_000_000.0)


def test_single_sample_uses_kernel_seconds():
    window = [(5000.0, 5000.05, 100_000)]
    rate = rate_from_window(window, last_kernel_s=0.05)
    assert rate == pytest.approx(2_000_000.0)


def test_empty_window():
    assert rate_from_window([]) == 0.0


def test_zero_span_without_kernel_is_zero():
    window = [(5.0, 5.0, 100_000)]
    assert rate_from_window(window, last_kernel_s=0.0) == 0.0


def test_pause_gap_included_in_wall_rate():
    # 1s mining, 3s bekleme, 1s mining → ortalama dusuk
    window = [(0.0, 1.0, 1_000_000), (4.0, 5.0, 1_000_000)]
    assert rate_from_window(window) == pytest.approx(400_000.0)


def test_kernel_only_label_helper():
    assert rate_kernel_only(1_000_000, 0.5) == pytest.approx(2_000_000.0)
