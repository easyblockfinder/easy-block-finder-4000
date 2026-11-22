"""Automatic idle mining policy — mode + work scale (0..1 of user capacity)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Optional

IdleMode = Literal["off", "active", "idle"]


@dataclass(frozen=True)
class IdlePolicyState:
    mode: IdleMode
    scale: float  # 0.0 .. 1.0 of configured capacity; 1.0 when feature off
    reason: str
    active_pct: int = 10
    idle_pct: int = 80


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
    active_pct = intensity while the user is using the PC (keyboard/mouse recently).
    idle_pct   = intensity after idle timeout with no input (AFK).

    Start Idle arms a session: stay on active_pct until either the user produces
    input once, or `timeout_s` wall time passes — then normal idle_s rules apply.
    That way AFK-at-start does not immediately jump to idle_pct.
    """

    enabled: bool = False
    timeout_s: int = 150
    active_pct: int = 10
    idle_pct: int = 80
    _mode: IdleMode = "off"
    _session_armed_mono: Optional[float] = None
    _session_seen_input: bool = False

    def configure(
        self,
        *,
        enabled: bool,
        timeout_s: object = 150,
        active_pct: object = 10,
        idle_pct: object = 80,
    ) -> None:
        self.enabled = bool(enabled)
        self.timeout_s = _clamp_timeout(timeout_s)
        self.active_pct = _clamp_pct(active_pct, 10)
        self.idle_pct = _clamp_pct(idle_pct, 80)
        if not self.enabled:
            self._mode = "off"
            self._session_armed_mono = None
            self._session_seen_input = False

    def arm_session(self) -> None:
        """Call when Start Idle begins mining — prefer active_pct first."""
        self._session_armed_mono = time.monotonic()
        self._session_seen_input = False
        if self.enabled:
            self._mode = "active"

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
                else "activity unknown — safe ACTIVE (using-PC intensity)"
            )
            return IdlePolicyState(
                mode="active",
                scale=self.active_pct / 100.0,
                reason=reason,
                active_pct=self.active_pct,
                idle_pct=self.idle_pct,
            )

        idle = max(0.0, float(idle_s))
        # Track that the user touched input since Start Idle (idle clock reset).
        if idle < 1.0:
            self._session_seen_input = True

        # Post-start hold: keep using-PC intensity until input seen or timeout elapsed.
        if self._session_armed_mono is not None and not self._session_seen_input:
            held = time.monotonic() - float(self._session_armed_mono)
            if held < float(self.timeout_s):
                self._mode = "active"
                return IdlePolicyState(
                    mode="active",
                    scale=self.active_pct / 100.0,
                    reason=(
                        f"Start Idle hold — using-PC intensity "
                        f"({held:.0f}/{self.timeout_s}s)"
                    ),
                    active_pct=self.active_pct,
                    idle_pct=self.idle_pct,
                )
            # Hold expired without input → fall through to normal idle_s rules.

        if idle >= float(self.timeout_s):
            self._mode = "idle"
            return IdlePolicyState(
                mode="idle",
                scale=self.idle_pct / 100.0,
                reason=f"AFK idle {idle:.0f}s ≥ {self.timeout_s}s",
                active_pct=self.active_pct,
                idle_pct=self.idle_pct,
            )

        # Recent input → using-PC intensity
        self._mode = "active"
        return IdlePolicyState(
            mode="active",
            scale=self.active_pct / 100.0,
            reason=f"using PC (idle {idle:.1f}s)",
            active_pct=self.active_pct,
            idle_pct=self.idle_pct,
        )


def normalize_idle_settings(data: dict) -> dict:
    """Sanitize settings blob fragment."""
    legacy_on = bool(data.get("auto_idle_mining", False))
    configured = bool(data.get("idle_settings_configured", False)) or legacy_on
    active = data.get("idle_active_pct")
    if active is None:
        active_pct = 10
    else:
        active_pct = _clamp_pct(active, 10)
    return {
        "auto_idle_mining": legacy_on,
        "idle_settings_configured": configured,
        "idle_timeout_s": _clamp_timeout(data.get("idle_timeout_s", 150)),
        "idle_active_pct": active_pct,
        "idle_idle_pct": _clamp_pct(data.get("idle_idle_pct", 80), 80),
    }
