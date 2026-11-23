"""CPU reference histogram + host-side WG sum with overflow detection."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from audit.thresholds import (
    AUDIT_DIFFICULTY_THRESHOLDS,
    hash_digest_meets_target,
    targets_for_thresholds,
)
from mining.bitcoin import hash256


@dataclass
class HistogramResult:
    counts: list[int]  # cumulative: meets difficulty >= threshold[i]
    attempts: int
    overflow: bool = False
    thresholds: tuple[float, ...] = AUDIT_DIFFICULTY_THRESHOLDS


@dataclass
class SessionHistogram:
    counts: list[int] = field(
        default_factory=lambda: [0] * len(AUDIT_DIFFICULTY_THRESHOLDS)
    )
    attempts: int = 0
    overflow: bool = False

    def add(self, batch: HistogramResult) -> None:
        self.attempts += int(batch.attempts)
        for i, c in enumerate(batch.counts):
            prev = self.counts[i]
            nxt = prev + int(c)
            if nxt < prev:
                self.overflow = True
                self.counts[i] = 2**64 - 1
            else:
                self.counts[i] = nxt
        if batch.overflow:
            self.overflow = True


def cpu_histogram_for_range(
    header80_prefix76: bytes,
    start_nonce: int,
    count: int,
    thresholds: tuple[float, ...] = AUDIT_DIFFICULTY_THRESHOLDS,
) -> HistogramResult:
    """Brute-force reference: every nonce hashed on CPU; padding not included."""
    if len(header80_prefix76) != 76:
        raise ValueError("header prefix must be 76 bytes")
    if count < 0:
        raise ValueError("count must be >= 0")
    targets = targets_for_thresholds(thresholds)
    counts = [0] * len(thresholds)
    for n in range(start_nonce, start_nonce + count):
        digest = hash256(header80_prefix76 + struct.pack("<I", n & 0xFFFFFFFF))
        for i, tgt in enumerate(targets):
            if hash_digest_meets_target(digest, tgt):
                counts[i] += 1
    return HistogramResult(counts=counts, attempts=int(count), overflow=False)


def sum_wg_histogram(
    hist_wg: list[int] | object,
    num_groups: int,
    n_thresh: int = 12,
) -> HistogramResult:
    """Sum per-workgroup ulong counters from GPU; detect uint64 overflow on accumulate."""
    import numpy as np

    arr = np.asarray(hist_wg, dtype=np.uint64).reshape(-1)
    expect = num_groups * n_thresh
    if arr.size < expect:
        raise ValueError(f"hist_wg too small: {arr.size} < {expect}")
    counts = [0] * n_thresh
    overflow = False
    attempts_check = 0
    for g in range(num_groups):
        for i in range(n_thresh):
            v = int(arr[g * n_thresh + i])
            prev = counts[i]
            nxt = prev + v
            if nxt < prev or nxt > 2**64 - 1:
                overflow = True
                counts[i] = 2**64 - 1
            else:
                counts[i] = nxt
            if i == 0:
                attempts_check += v  # not attempts — threshold0 count
    return HistogramResult(counts=counts, attempts=0, overflow=overflow)
