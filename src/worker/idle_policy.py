"""Automatic idle mining policy — mode + work scale (0..1 of user capacity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

IdleMode = Literal["off", "active", "idle"]


@dataclass(frozen=True)
class IdlePolicyState:
    mode: IdleMode
    scale: float  # 0.0 .. 1.0 of configured capacity; 1.0 when feature off
    reason: str
    active_pct: int = 10
    idle_pct: int = 100


def _clamp_pct(raw: object, default: int) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, min(100, n))


def _clamp_timeout(raw: object, default: int = 150) -> int:
    try:
        n = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(5, min(3600, n))


@dataclass
class IdleMiningPolicy:
    """
    ACTIVE → IDLE only after timeout.
    IDLE → ACTIVE ASAP on activity (idle_s < timeout, typically near 0).
    force_active (sleep/session): stay ACTIVE and treat timeout as reset.
    idle_s is None (API failure): safe ACTIVE.
    """

    enabled: bool = False
    timeout_s: int = 150
    active_pct: int = 10
    idle_pct: int = 100
    _mode: IdleMode = "off"

    def configure(
        self,
        *,
        enabled: bool,
        timeout_s: object = 150,
        active_pct: object = 10,
        idle_pct: object = 100,
    ) -> None:
        self.enabled = bool(enabled)
        self.timeout_s = _clamp_timeout(timeout_s)
        self.active_pct = _clamp_pct(active_pct, 10)
        self.idle_pct = _clamp_pct(idle_pct, 100)
        if not self.enabled:
            self._mode = "off"

    def reset_to_active(self) -> None:
        """After sleep/session resume or activity-monitor failure recovery."""
        if self.enabled:
            self._mode = "active"
        else:
            self._mode = "off"

    def evaluate(
        self,
        *,
        idle_s: Optional[float],
        force_active: bool = False,
    ) -> IdlePolicyState:
        if not self.enabled:
            self._mode = "off"
            return IdlePolicyState(
                mode="off",
                scale=1.0,
                reason="auto-idle off",
                active_pct=self.active_pct,
                idle_pct=self.idle_pct,
            )

        if force_active or idle_s is None:
            self._mode = "active"
            reason = (
                "forced ACTIVE (sleep/session)"
                if force_active
                else "activity unknown — safe ACTIVE"
            )
            return IdlePolicyState(
                mode="active",
                scale=self.active_pct / 100.0,
                reason=reason,
                active_pct=self.active_pct,
                idle_pct=self.idle_pct,
            )

        idle = max(0.0, float(idle_s))
        if idle >= float(self.timeout_s):
            self._mode = "idle"
            return IdlePolicyState(
                mode="idle",
                scale=self.idle_pct / 100.0,
                reason=f"idle {idle:.0f}s ≥ {self.timeout_s}s",
                active_pct=self.active_pct,
                idle_pct=self.idle_pct,
            )

        # Any activity below timeout → ACTIVE immediately (including IDLE→ACTIVE).
        self._mode = "active"
        return IdlePolicyState(
            mode="active",
            scale=self.active_pct / 100.0,
            reason=f"user active (idle {idle:.1f}s)",
            active_pct=self.active_pct,
            idle_pct=self.idle_pct,
        )


def normalize_idle_settings(data: dict) -> dict:
    """Sanitize settings blob fragment."""
    return {
        "auto_idle_mining": bool(data.get("auto_idle_mining", False)),
        "idle_timeout_s": _clamp_timeout(data.get("idle_timeout_s", 150)),
        "idle_active_pct": _clamp_pct(data.get("idle_active_pct", 10), 10),
        "idle_idle_pct": _clamp_pct(data.get("idle_idle_pct", 100), 100),
    }
