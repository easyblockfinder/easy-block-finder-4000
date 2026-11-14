"""External motor counter accumulation — fold without racing with generation."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ShareSnapshot:
    accepted: int = 0
    rejected: int = 0
    engine_fee_shares: int = 0
    unattributed_shares: int = 0
    generation: int = 0


@dataclass
class ManagedShareAccum:
    """
    process_* = contributions from the active engine instance
    accum_* = folded total from retired engine instances
    stop() and miner-thread _halt_* may run concurrently -> RLock.
    """

    accum_user: int = 0
    accum_don: int = 0
    accum_fee: int = 0
    accum_unattr: int = 0
    accum_rej: int = 0
    process_acc: int = 0
    process_fee: int = 0
    process_unattr: int = 0
    process_rej: int = 0
    donation_active: bool = False
    active_gen: int = 0
    max_retired_gen: int = 0
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def set_donation_active(self, active: bool) -> None:
        with self._lock:
            self.donation_active = bool(active)

    def next_generation(self) -> int:
        with self._lock:
            self.active_gen += 1
            self.process_acc = 0
            self.process_fee = 0
            self.process_unattr = 0
            self.process_rej = 0
            return self.active_gen

    def accepts(self, generation: int) -> bool:
        with self._lock:
            return (
                generation == self.active_gen
                and generation > self.max_retired_gen
                and generation > 0
            )

    def apply_snapshot(self, snap: Any, generation: int) -> bool:
        """Live callback. Retired generation → False."""
        with self._lock:
            if not (
                generation == self.active_gen
                and generation > self.max_retired_gen
                and generation > 0
            ):
                return False
            self.process_acc = int(getattr(snap, "accepted", 0) or 0)
            self.process_fee = int(getattr(snap, "engine_fee_shares", 0) or 0)
            self.process_unattr = int(getattr(snap, "unattributed_shares", 0) or 0)
            self.process_rej = int(getattr(snap, "rejected", 0) or 0)
            return True

    def retire_with_final(self, generation: int, final_snap: Optional[Any]) -> bool:
        """
        Retire engine: apply final snapshot once, fold, close generation.
        Second / concurrent call for the same gen is a no-op (under lock).
        """
        with self._lock:
            if generation <= self.max_retired_gen:
                return False
            if generation != self.active_gen:
                self.max_retired_gen = max(self.max_retired_gen, generation)
                return False
            if final_snap is not None:
                self.process_acc = int(getattr(final_snap, "accepted", 0) or 0)
                self.process_fee = int(
                    getattr(final_snap, "engine_fee_shares", 0) or 0
                )
                self.process_unattr = int(
                    getattr(final_snap, "unattributed_shares", 0) or 0
                )
                self.process_rej = int(getattr(final_snap, "rejected", 0) or 0)
            self._fold_unlocked()
            self.max_retired_gen = generation
            self.process_acc = 0
            self.process_fee = 0
            self.process_unattr = 0
            self.process_rej = 0
            return True

    def _fold_unlocked(self) -> None:
        if self.donation_active:
            self.accum_don += self.process_acc
        else:
            self.accum_user += self.process_acc
        self.accum_fee += self.process_fee
        self.accum_unattr += self.process_unattr
        self.accum_rej += self.process_rej

    @property
    def display_accepted(self) -> int:
        with self._lock:
            if self.donation_active:
                return self.accum_user
            return self.accum_user + self.process_acc

    @property
    def display_donation(self) -> int:
        with self._lock:
            if self.donation_active:
                return self.accum_don + self.process_acc
            return self.accum_don

    @property
    def display_fee(self) -> int:
        with self._lock:
            return self.accum_fee + self.process_fee

    @property
    def display_unattr(self) -> int:
        with self._lock:
            return self.accum_unattr + self.process_unattr

    @property
    def display_rejected(self) -> int:
        with self._lock:
            return self.accum_rej + self.process_rej
