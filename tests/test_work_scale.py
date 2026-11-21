from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.work_scale import scaled_batch_sleep  # noqa: E402


def test_full_scale_matches_ladder_level_4():
    batch, sleep = scaled_batch_sleep(4, 1.0)
    assert batch == 2_097_152
    assert sleep == 0.002


def test_zero_scale_pauses():
    batch, sleep = scaled_batch_sleep(8, 0.0)
    assert batch == 0
    assert sleep == 0.0


def test_partial_scale_under_ceiling():
    full_b, _ = scaled_batch_sleep(8, 1.0)
    b10, s10 = scaled_batch_sleep(8, 0.10)
    assert 0 < b10 <= full_b
    assert s10 > 0.0


def test_scale_never_exceeds_base_batch():
    base_b, _ = scaled_batch_sleep(5, 1.0)
    b, _ = scaled_batch_sleep(5, 0.99)
    assert b <= base_b
