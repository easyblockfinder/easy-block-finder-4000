"""Start Idle session state machine — mining starts immediately at Active intensity."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class IdleSessionState(str, Enum):
    STOPPED = "STOPPED"
    # Kept for recovery if miner is up while UI briefly lagged.
    WAITING_FOR_IDLE = "WAITING_FOR_IDLE"
    MINING_IDLE = "MINING_IDLE"
    MINING_ACTIVE = "MINING_ACTIVE"


def initial_mining_state_from_activity(
    *, idle_s: Optional[float], timeout_s: int
) -> IdleSessionState:
    """
    Start Idle begins mining immediately:
    - already idle (idle_s ≥ timeout) → MINING_IDLE (idle intensity)
    - otherwise → MINING_ACTIVE (active intensity %)
    """
    t = max(5, int(timeout_s))
    if idle_s is not None and float(idle_s) >= float(t):
        return IdleSessionState.MINING_IDLE
    return IdleSessionState.MINING_ACTIVE


def mining_state_from_policy_mode(mode: str) -> IdleSessionState:
    """Map policy ACTIVE/IDLE → session mining states."""
    if mode == "idle":
        return IdleSessionState.MINING_IDLE
    return IdleSessionState.MINING_ACTIVE


def should_enable_idle_policy(
    state: IdleSessionState, *, miner_running: bool
) -> bool:
    """Idle scale/pause policy is on whenever a Start Idle session is mining."""
    if state in (IdleSessionState.MINING_IDLE, IdleSessionState.MINING_ACTIVE):
        return True
    if state == IdleSessionState.WAITING_FOR_IDLE and miner_running:
        return True
    return False


def promote_after_miner_start(
    state: IdleSessionState,
    *,
    idle_s: Optional[float] = None,
    timeout_s: int = 150,
) -> IdleSessionState:
    """After miner start, land on ACTIVE or IDLE from current activity."""
    if state in (
        IdleSessionState.WAITING_FOR_IDLE,
        IdleSessionState.STOPPED,
    ):
        return initial_mining_state_from_activity(
            idle_s=idle_s, timeout_s=timeout_s
        )
    return state
