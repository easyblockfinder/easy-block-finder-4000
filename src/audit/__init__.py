"""Mining Statistical Audit — opt-in; production mining path unchanged when off."""

from __future__ import annotations

from audit.thresholds import (
    AUDIT_DIFFICULTY_THRESHOLDS,
    audit_target_words_flat,
    targets_for_thresholds,
)

__all__ = [
    "AUDIT_DIFFICULTY_THRESHOLDS",
    "audit_target_words_flat",
    "targets_for_thresholds",
]
