from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from game.pan_fold import fold_pan_y_into_bias  # noqa: E402


def _wy(bias: int, pan_y: float, sy: float, cs: float) -> float:
    return bias + (sy - pan_y) / cs


def test_fold_deep_negative_pan_raises_bias_and_keeps_world_y():
    cs = 32.0
    limit = 1500.0
    sy = 400.0
    pan_y = -5000.0
    bias = 100
    before = _wy(bias, pan_y, sy, cs)
    new_pan, new_bias = fold_pan_y_into_bias(pan_y, bias, cs, limit)
    assert new_bias > bias
    assert new_pan >= -limit
    assert abs(_wy(new_bias, new_pan, sy, cs) - before) < 1e-9


def test_fold_positive_pan_lowers_bias_and_keeps_world_y():
    cs = 32.0
    limit = 1500.0
    sy = 400.0
    pan_y = 5000.0
    bias = 200
    before = _wy(bias, pan_y, sy, cs)
    new_pan, new_bias = fold_pan_y_into_bias(pan_y, bias, cs, limit)
    assert new_bias < bias
    assert new_pan <= limit
    assert abs(_wy(new_bias, new_pan, sy, cs) - before) < 1e-9


def test_repeated_deep_folds_never_freeze_at_zero_bias():
    """Old bug: bias decreased on deep fold → stuck at 0 and pan undone forever."""
    cs = 32.0
    limit = 1500.0
    pan_y = 0.0
    bias = 0
    for _ in range(200):
        pan_y -= 96.0  # scratch follow tick downward
        pan_y, bias = fold_pan_y_into_bias(pan_y, bias, cs, limit)
    assert bias > 0
    assert pan_y >= -limit - cs
