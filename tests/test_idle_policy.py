from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.idle_policy import IdleMiningPolicy, normalize_idle_settings  # noqa: E402


def test_defaults_off_full_scale():
    p = IdleMiningPolicy()
    st = p.evaluate(idle_s=9999)
    assert st.mode == "off"
    assert st.scale == 1.0


def test_using_pc_uses_active_pct_afk_uses_idle_pct():
    """active_pct = while using PC; idle_pct = while AFK — must not be swapped."""
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    st = p.evaluate(idle_s=10)
    assert st.mode == "active"
    assert abs(st.scale - 0.10) < 1e-9
    st2 = p.evaluate(idle_s=150)
    assert st2.mode == "idle"
    assert abs(st2.scale - 1.0) < 1e-9


def test_afk_to_using_pc_immediate():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=150, active_pct=10, idle_pct=100)
    p.evaluate(idle_s=200)
    st = p.evaluate(idle_s=0.05)
    assert st.mode == "active"
    assert abs(st.scale - 0.10) < 1e-9


def test_start_idle_arm_holds_using_pc_intensity_while_already_afk():
    """Already AFK at Start Idle → still use active_pct until hold expires or input."""
    p = IdleMiningPolicy()
    # timeout clamps to min 5s
    p.configure(enabled=True, timeout_s=5, active_pct=25, idle_pct=100)
    p.arm_session()
    st = p.evaluate(idle_s=999)
    assert st.mode == "active"
    assert abs(st.scale - 0.25) < 1e-9
    time.sleep(5.15)
    st2 = p.evaluate(idle_s=999)
    assert st2.mode == "idle"
    assert abs(st2.scale - 1.0) < 1e-9


def test_start_idle_arm_ends_hold_on_input():
    p = IdleMiningPolicy()
    p.configure(enabled=True, timeout_s=30, active_pct=40, idle_pct=100)
    p.arm_session()
    p.evaluate(idle_s=999)  # hold active
    st = p.evaluate(idle_s=0.2)  # input seen
    assert st.mode == "active"
    assert abs(st.scale - 0.40) < 1e-9
    # Later AFK without new arm → idle_pct
    st2 = p.evaluate(idle_s=60)
    assert st2.mode == "idle"
    assert abs(st2.scale - 1.0) < 1e-9


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
    assert out["idle_settings_configured"] is False
    assert out["idle_timeout_s"] == 150
    assert out["idle_active_pct"] == 10
    assert out["idle_idle_pct"] == 80


def test_legacy_auto_idle_marks_configured():
    out = normalize_idle_settings({"auto_idle_mining": True, "idle_timeout_s": 200})
    assert out["idle_settings_configured"] is True
    assert out["idle_timeout_s"] == 200
