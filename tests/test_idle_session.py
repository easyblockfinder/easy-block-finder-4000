"""Start Idle session — immediate start at Active intensity."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))

from worker.idle_session import (  # noqa: E402
    IdleSessionState,
    initial_mining_state_from_activity,
    mining_state_from_policy_mode,
    promote_after_miner_start,
    should_enable_idle_policy,
)


def test_start_idle_begins_active_when_user_not_idle():
    st = initial_mining_state_from_activity(idle_s=5.0, timeout_s=150)
    assert st == IdleSessionState.MINING_ACTIVE


def test_start_idle_begins_idle_when_already_idle():
    st = initial_mining_state_from_activity(idle_s=200.0, timeout_s=150)
    assert st == IdleSessionState.MINING_IDLE


def test_activity_unknown_defaults_to_active_intensity():
    st = initial_mining_state_from_activity(idle_s=None, timeout_s=150)
    assert st == IdleSessionState.MINING_ACTIVE


def test_mining_state_mapping():
    assert mining_state_from_policy_mode("idle") == IdleSessionState.MINING_IDLE
    assert mining_state_from_policy_mode("active") == IdleSessionState.MINING_ACTIVE


def test_policy_on_while_mining():
    assert (
        should_enable_idle_policy(IdleSessionState.MINING_ACTIVE, miner_running=True)
        is True
    )
    assert (
        should_enable_idle_policy(IdleSessionState.MINING_IDLE, miner_running=True)
        is True
    )
    assert (
        should_enable_idle_policy(IdleSessionState.STOPPED, miner_running=False)
        is False
    )


def test_promote_uses_activity():
    assert (
        promote_after_miner_start(
            IdleSessionState.WAITING_FOR_IDLE, idle_s=1.0, timeout_s=150
        )
        == IdleSessionState.MINING_ACTIVE
    )
    assert (
        promote_after_miner_start(
            IdleSessionState.WAITING_FOR_IDLE, idle_s=999.0, timeout_s=150
        )
        == IdleSessionState.MINING_IDLE
    )
