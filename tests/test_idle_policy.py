from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.idle_policy import IdleMiningPolicy, normalize_idle_settings  # noqa: E402


def test_defaults_off_full_scale():
    p = IdleMiningPolicy()
    st = p.evaluate(idle_s=9999)
    assert st.mode == "off"
    assert st.scale == 1.0


def test_active_to_idle_after_timeout():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    st = p.evaluate(idle_s=10)
    assert st.mode == "active"
    assert abs(st.scale - 0.10) < 1e-9
    st2 = p.evaluate(idle_s=150)
    assert st2.mode == "idle"
    assert abs(st2.scale - 1.0) < 1e-9


def test_idle_to_active_immediate():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    p.evaluate(idle_s=200)
    st = p.evaluate(idle_s=0.05)
    assert st.mode == "active"
    assert abs(st.scale - 0.10) < 1e-9


def test_force_active_and_none_idle():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=30, active_pct=25, idle_pct=80)
    p.evaluate(idle_s=100)
    st = p.evaluate(idle_s=100, force_active=True)
    assert st.mode == "active"
    assert abs(st.scale - 0.25) < 1e-9
    st2 = p.evaluate(idle_s=None)
    assert st2.mode == "active"


def test_zero_pct_scale():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=10, active_pct=0, idle_pct=0)
    assert p.evaluate(idle_s=0).scale == 0.0
    assert p.evaluate(idle_s=20).scale == 0.0


def test_normalize_idle_settings_existing_user():
    out = normalize_idle_settings({})
    assert out["auto_idle_mining"] is False
    assert out["idle_timeout_s"] == 150
    assert out["idle_active_pct"] == 10
    assert out["idle_idle_pct"] == 100
