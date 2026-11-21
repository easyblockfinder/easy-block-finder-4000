from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.work_scale import (  # noqa: E402
    adaptive_duty_sleep,
    intensity_batch_sleep,
    scaled_batch_sleep,
    update_ema,
)


def test_full_scale_matches_ladder_level_4():
    batch, sleep = intensity_batch_sleep(4)
    assert batch == 2_097_152
    assert sleep == 0.002
    assert scaled_batch_sleep(4, 1.0) == (batch, sleep)


def test_zero_scale_pauses():
    batch, sleep = scaled_batch_sleep(8, 0.0)
    assert batch == 0
    assert sleep == 0.0


def test_adaptive_s1_equals_base_sleep_only():
    # S=1 → B; T does not change wait (no double-apply of B)
    assert adaptive_duty_sleep(0.050, 0.002, 1.0) == 0.002
    assert adaptive_duty_sleep(1.0, 0.0, 1.0) == 0.0


def test_adaptive_formula_with_measured_t():
    t, b, s = 0.040, 0.002, 0.10
    expect = max(0.0, ((t + b) / s) - t)
    assert abs(adaptive_duty_sleep(t, b, s) - expect) < 1e-12


def test_adaptive_different_batch_times():
    b = 0.002
    s = 0.25
    short = adaptive_duty_sleep(0.01, b, s)
    long = adaptive_duty_sleep(0.10, b, s)
    assert long > short


def test_ema_smooths():
    e = update_ema(None, 0.10, alpha=0.5)
    assert abs(e - 0.10) < 1e-12
    e2 = update_ema(e, 0.00, alpha=0.5)
    assert abs(e2 - 0.05) < 1e-12
