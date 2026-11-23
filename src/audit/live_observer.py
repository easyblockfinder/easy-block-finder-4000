"""
Live Pool Audit observer — attach to MiningController when enabled.

Does not alter share semantics; when active, controller should call search_audit
instead of search so histogram covers the real hash population.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from audit.histogram import HistogramResult, SessionHistogram
from audit.stats import evaluate_disjoint_bands, evaluate_focus_cumulative
from audit.work_family import family_from_job
from mining.best_hash import difficulty_from_hash_int, hash_be_hex_to_int


@dataclass
class LiveAuditSnapshot:
    enabled: bool = True
    attempts: int = 0
    unique_attempts: int = 0
    duplicate_range_count: int = 0
    unique_work_prefixes: int = 0
    identical_notify_count: int = 0
    extranonce2_wrap_count: int = 0
    cpu_verify_failures: int = 0
    truncation_count: int = 0
    pool_difficulty: float | None = None
    highest_submitted_diff: float | None = None
    highest_rejected_diff: float | None = None
    highest_accepted_diff: float | None = None
    gpu_best_diff: float | None = None
    histogram_counts: list[int] = field(default_factory=list)
    histogram_overflow: bool = False
    band_evals: list[dict[str, Any]] = field(default_factory=list)
    focus_evals: list[dict[str, Any]] = field(default_factory=list)
    audit_kernel_s: float = 0.0
    production_probe_s: float | None = None
    overhead_percent: float | None = None
    message: str = ""


class LiveAuditObserver:
    def __init__(self) -> None:
        self._hist = SessionHistogram()
        self._seen_ranges: set[tuple[str, str, int, int]] = set()
        self._prefixes: set[bytes] = set()
        self._families_seen: set[str] = set()
        self._identical_notify = 0
        self._en2_wraps = 0
        self._last_en2: dict[str, int] = {}
        self._cpu_fail = 0
        self._trunc = 0
        self._pool_diff: float | None = None
        self._hi_sub: float | None = None
        self._hi_rej: float | None = None
        self._hi_acc: float | None = None
        self._gpu_best: float | None = None
        self._audit_s = 0.0
        self._unique_attempts = 0
        self._duplicate_range_count = 0

    def on_difficulty(self, diff: float) -> None:
        self._pool_diff = float(diff)

    def on_notify(self, job: Any, clean: bool) -> None:
        fid = family_from_job(job)
        if fid in self._families_seen:
            self._identical_notify += 1
        self._families_seen.add(fid)
        en2 = int(getattr(job, "extranonce2", 0) or 0)
        prev = self._last_en2.get(fid)
        if prev is not None and en2 < prev:
            self._en2_wraps += 1
        self._last_en2[fid] = en2

    def on_extranonce_bump(self, job: Any, old_en2: int, new_en2: int) -> None:
        if int(new_en2) < int(old_en2):
            self._en2_wraps += 1

    def begin_batch_timer(self) -> float:
        return time.perf_counter()

    def on_batch(
        self,
        *,
        family_id: str,
        extranonce2_hex: str,
        header_prefix: bytes,
        start_nonce: int,
        count: int,
        result: Any,
        hist: HistogramResult,
        t0: float,
        cpu_verify_failed: bool = False,
    ) -> None:
        self._audit_s += max(0.0, time.perf_counter() - t0)
        self._hist.add(hist)
        self._prefixes.add(bytes(header_prefix))
        key = (family_id, extranonce2_hex, int(start_nonce), int(count))
        if key in self._seen_ranges:
            self._duplicate_range()
        else:
            self._seen_ranges.add(key)
            self._unique_attempts += int(count)
        if getattr(result, "truncated", False):
            self._trunc += 1
        if cpu_verify_failed:
            self._cpu_fail += 1
        hx = getattr(result, "best_hash_be_hex", None)
        if hx:
            try:
                d = difficulty_from_hash_int(hash_be_hex_to_int(hx))
                if self._gpu_best is None or d > self._gpu_best:
                    self._gpu_best = d
            except ValueError:
                pass

    def _duplicate_range(self) -> None:
        self._duplicate_range_count += 1

    def on_submit_result(
        self,
        *,
        accepted: bool,
        rejected: bool,
        share_difficulty: float | None,
    ) -> None:
        if share_difficulty is None:
            return
        d = float(share_difficulty)
        if self._hi_sub is None or d > self._hi_sub:
            self._hi_sub = d
        if accepted and (self._hi_acc is None or d > self._hi_acc):
            self._hi_acc = d
        if rejected and (self._hi_rej is None or d > self._hi_rej):
            self._hi_rej = d

    def snapshot(self) -> LiveAuditSnapshot:
        n = self._hist.attempts
        bands = evaluate_disjoint_bands(n, self._hist.counts) if n else []
        focus = evaluate_focus_cumulative(n, self._hist.counts) if n else []
        return LiveAuditSnapshot(
            attempts=n,
            unique_attempts=self._unique_attempts,
            duplicate_range_count=self._duplicate_range_count,
            unique_work_prefixes=len(self._prefixes),
            identical_notify_count=self._identical_notify,
            extranonce2_wrap_count=self._en2_wraps,
            cpu_verify_failures=self._cpu_fail,
            truncation_count=self._trunc,
            pool_difficulty=self._pool_diff,
            highest_submitted_diff=self._hi_sub,
            highest_rejected_diff=self._hi_rej,
            highest_accepted_diff=self._hi_acc,
            gpu_best_diff=self._gpu_best,
            histogram_counts=list(self._hist.counts),
            histogram_overflow=self._hist.overflow,
            band_evals=[asdict(b) for b in bands],
            focus_evals=[asdict(b) for b in focus],
            audit_kernel_s=self._audit_s,
            message=f"Live audit N={n:,}",
        )
