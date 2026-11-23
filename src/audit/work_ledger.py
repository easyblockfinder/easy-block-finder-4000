"""
Stratum Work Ledger — opt-in, low-cost duplicate search-space diagnostics.

Attempts and duplicate math use ONLY completed GPU batches (result.scanned).
Synthetic / time-budget scripts must set measurement_source explicitly and must
never be labeled as gpu_completed_batches.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from audit.work_family import family_from_job, work_family_id

# Provenance labels — never conflate synthetic with GPU.
MEASUREMENT_GPU = "gpu_completed_batches"
MEASUREMENT_SYNTHETIC = "synthetic_time_budget_not_gpu"


def overlap_len(a0: int, a1: int, b0: int, b1: int) -> int:
    """Overlap length of half-open [a0,a1) and [b0,b1)."""
    lo = max(int(a0), int(b0))
    hi = min(int(a1), int(b1))
    return max(0, hi - lo)


def merge_coverage_unique(intervals: list[tuple[int, int]]) -> tuple[int, int]:
    """
    Given half-open intervals, return (unique_coverage, duplicate_coverage).
    duplicate = sum(lengths) - unique.
    """
    if not intervals:
        return 0, 0
    sorted_iv = sorted((int(a), int(b)) for a, b in intervals if int(b) > int(a))
    if not sorted_iv:
        return 0, 0
    total = sum(b - a for a, b in sorted_iv)
    merged: list[list[int]] = [[sorted_iv[0][0], sorted_iv[0][1]]]
    for a, b in sorted_iv[1:]:
        if a < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        elif a == merged[-1][1]:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    unique = sum(b - a for a, b in merged)
    return unique, total - unique


def coverage_unique_len(merged: list[tuple[int, int]]) -> int:
    return sum(max(0, int(b) - int(a)) for a, b in merged)


def insert_interval_merged(
    merged: list[tuple[int, int]], start: int, end: int
) -> tuple[int, list[tuple[int, int]]]:
    """
    Insert [start,end) into a sorted non-overlapping merged list.
    Returns (newly_covered_unique_hashes, new_merged_list).
    """
    a0, a1 = int(start), int(end)
    if a1 <= a0:
        return 0, merged
    if not merged:
        return a1 - a0, [(a0, a1)]

    prev_u = coverage_unique_len(merged)
    out: list[tuple[int, int]] = []
    i = 0
    n = len(merged)
    # copy intervals strictly before a0
    while i < n and merged[i][1] < a0:
        out.append(merged[i])
        i += 1
    lo, hi = a0, a1
    while i < n and merged[i][0] <= hi:
        lo = min(lo, merged[i][0])
        hi = max(hi, merged[i][1])
        i += 1
    out.append((lo, hi))
    while i < n:
        out.append(merged[i])
        i += 1
    new_u = coverage_unique_len(out)
    return max(0, new_u - prev_u), out


def mask_secret(value: str, keep: int = 3) -> str:
    s = (value or "").strip()
    if not s:
        return ""
    if len(s) <= keep * 2:
        return "***"
    return f"{s[:keep]}***{s[-keep:]}"


def _fp(value: str) -> str:
    """Short fingerprint for extranonce1 etc. (not reversible to full secret in UI)."""
    s = (value or "").strip().lower()
    if not s:
        return ""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


@dataclass
class _JobState:
    job_id: str
    family_id: str
    session_id: int
    clean: bool
    started_ts: float
    ended_ts: float | None = None
    hashes_scanned: int = 0
    batches_completed: int = 0
    allocated_count_sum: int = 0
    cut_by_notify: bool = False
    cut_reason: str = ""
    en2_ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)


class StratumWorkLedger:
    def __init__(self, *, measurement_source: str = MEASUREMENT_GPU) -> None:
        src = (measurement_source or MEASUREMENT_GPU).strip()
        if src not in (MEASUREMENT_GPU, MEASUREMENT_SYNTHETIC):
            raise ValueError(f"Unknown measurement_source: {src}")
        self.measurement_source = src
        self._notify_events: list[dict[str, Any]] = []
        self._jobs: dict[str, _JobState] = {}
        self._current_job_id: str | None = None
        self._family_to_job_ids: dict[str, set[str]] = {}
        self._identical_work_notifications = 0
        self._reconnects = 0
        self._en1_changes = 0
        self._last_en1: str | None = None
        self._last_en1_fp: str | None = None
        self._last_session: int | None = None
        self._last_notify_fields: dict[str, str] | None = None
        self._total_attempts = 0
        self._aborted_inflight = 0
        self._jobs_cut_by_notify = 0
        self._hashes_on_cut_jobs = 0
        # Global coverage per (family, en2): list of [start, end) from COMPLETED scanned
        self._coverage: dict[tuple[str, str], list[tuple[int, int]]] = {}
        self._gpu_best_timeline: list[dict[str, Any]] = []
        self._acc_best_timeline: list[dict[str, Any]] = []
        self._subscribe_events: list[dict[str, Any]] = []
        self._batches_completed = 0
        self._overhead_s_total = 0.0
        self._overhead_calls = 0
        self._kernel_s_total = 0.0
        self._hashrate_samples: list[dict[str, Any]] = []
        self._created_ts = time.time()

    def on_subscribe(
        self,
        *,
        session_id: int,
        extranonce1: str,
        extranonce2_size: int,
    ) -> None:
        """Idempotent for same session+en1; records reconnect / en1 change otherwise."""
        now = time.time()
        en1 = (extranonce1 or "").strip()
        fp = _fp(en1)
        sid = int(session_id)
        if (
            self._last_session is not None
            and self._last_en1 is not None
            and sid == int(self._last_session)
            and en1 == self._last_en1
        ):
            return
        if self._last_session is not None and sid != int(self._last_session):
            self._reconnects += 1
        if self._last_en1 is not None and en1 != self._last_en1:
            self._en1_changes += 1
        self._last_en1 = en1
        self._last_en1_fp = fp
        self._last_session = sid
        self._subscribe_events.append(
            {
                "ts": now,
                "session_id": sid,
                "extranonce1_fp": fp,
                "extranonce1_raw": en1,
                "extranonce2_size": int(extranonce2_size),
            }
        )

    def on_notify(
        self,
        job: Any,
        clean: bool,
        session_id: int,
        payout_address: str = "",
    ) -> None:
        now = time.time()
        fid = family_from_job(job)
        jid = str(job.job_id)
        fields = {
            "job_id": jid,
            "prevhash": str(job.prevhash),
            "coinb1": str(job.coinb1),
            "coinb2": str(job.coinb2),
            "merkle_branches": "|".join(str(x) for x in job.merkle_branches),
            "version": str(job.version),
            "nbits": str(job.nbits),
            "ntime": str(job.ntime),
            "extranonce1": str(job.extranonce1),
            "extranonce2_size": str(int(job.extranonce2_size)),
        }
        changed: list[str] = []
        if self._last_notify_fields is not None:
            for k, v in fields.items():
                if self._last_notify_fields.get(k) != v:
                    changed.append(k)
        else:
            changed = ["(first_notify)"]

        prior_jobs = self._family_to_job_ids.setdefault(fid, set())
        identical_new_job = bool(prior_jobs) and jid not in prior_jobs
        if identical_new_job:
            self._identical_work_notifications += 1
        prior_jobs.add(jid)

        # Close previous job clock + mark cut-by-notify
        if self._current_job_id and self._current_job_id in self._jobs:
            prev = self._jobs[self._current_job_id]
            if prev.ended_ts is None:
                prev.ended_ts = now
            if not prev.cut_by_notify:
                prev.cut_by_notify = True
                prev.cut_reason = "new_notify"
                self._jobs_cut_by_notify += 1
                self._hashes_on_cut_jobs += int(prev.hashes_scanned)

        st = _JobState(
            job_id=jid,
            family_id=fid,
            session_id=int(session_id),
            clean=bool(clean),
            started_ts=now,
        )
        self._jobs[jid] = st
        self._current_job_id = jid
        self._last_notify_fields = fields

        self._notify_events.append(
            {
                "ts": now,
                "job_id": jid,
                "session_id": int(session_id),
                "clean_jobs": bool(clean),
                "work_family_id": fid,
                "changed_fields": changed,
                "identical_family_new_job_id": identical_new_job,
                "extranonce1_fp": _fp(str(job.extranonce1)),
                "extranonce2_size": int(job.extranonce2_size),
                "ntime": str(job.ntime),
                "nbits": str(job.nbits),
                "prevhash_fp": _fp(str(job.prevhash)),
                "payout_address_masked": mask_secret(payout_address),
                "coinb1_masked": mask_secret(str(job.coinb1), keep=2),
                "coinb2_masked": mask_secret(str(job.coinb2), keep=2),
            }
        )

    def on_gpu_batch_completed(
        self,
        *,
        job_id: str,
        work_family_id: str,
        extranonce2_hex: str,
        start_nonce: int,
        allocated_count: int,
        scanned: int,
        kernel_s: float = 0.0,
    ) -> None:
        """
        Record one completed production-kernel batch.
        ATTEMPTS += scanned only. Coverage interval = [start, start+scanned).
        """
        jid = str(job_id)
        st = self._jobs.get(jid)
        if st is None:
            return
        scanned_n = int(scanned)
        if scanned_n <= 0:
            return
        en2 = (extranonce2_hex or "").lower()
        start = int(start_nonce) & 0xFFFFFFFF
        end = start + scanned_n
        if end > 0x100000000:
            end = 0x100000000
            scanned_n = max(0, end - start)
            if scanned_n <= 0:
                return

        # Prefer family from notify state; allow caller override if present
        fid = (work_family_id or st.family_id or "").strip() or st.family_id
        key = (fid, en2)
        existing = self._coverage.get(key, [])
        newly_unique, merged = insert_interval_merged(existing, start, end)
        _dup = max(0, scanned_n - newly_unique)
        self._coverage[key] = merged
        # Per-job raw ranges kept coalesced lightly for diagnostics (cap growth)
        jr = st.en2_ranges.setdefault(en2, [])
        if jr and jr[-1][1] == start:
            jr[-1] = (jr[-1][0], end)
        else:
            jr.append((start, end))
            if len(jr) > 64:
                # Compact job-local view; global _coverage remains authoritative
                _, jr_m = insert_interval_merged([], jr[0][0], jr[0][1])
                for a, b in jr[1:]:
                    _, jr_m = insert_interval_merged(jr_m, a, b)
                st.en2_ranges[en2] = jr_m
        st.hashes_scanned += scanned_n
        st.batches_completed += 1
        st.allocated_count_sum += max(0, int(allocated_count))
        self._total_attempts += scanned_n
        self._batches_completed += 1
        if kernel_s > 0:
            self._kernel_s_total += float(kernel_s)

    def on_batch_allocated(
        self,
        job_id: str,
        extranonce2_hex: str,
        start_nonce: int,
        count: int,
        scanned: int,
    ) -> None:
        """Backward-compatible alias → completed GPU path (scanned drives coverage)."""
        st = self._jobs.get(str(job_id))
        fid = st.family_id if st is not None else ""
        self.on_gpu_batch_completed(
            job_id=str(job_id),
            work_family_id=fid,
            extranonce2_hex=str(extranonce2_hex),
            start_nonce=int(start_nonce),
            allocated_count=int(count),
            scanned=int(scanned),
        )

    def on_inflight_aborted(self, n: int = 1, *, reason: str = "epoch_session") -> None:
        self._aborted_inflight += max(0, int(n))

    def note_overhead_s(self, seconds: float) -> None:
        s = max(0.0, float(seconds))
        self._overhead_s_total += s
        self._overhead_calls += 1

    def note_hashrate(self, hashrate: float) -> None:
        hs = float(hashrate)
        if hs < 0:
            return
        # Cap sample list
        self._hashrate_samples.append({"ts": time.time(), "hashrate": hs})
        if len(self._hashrate_samples) > 500:
            self._hashrate_samples = self._hashrate_samples[-500:]

    def on_gpu_best(self, difficulty: float, hash_be_hex: str = "") -> None:
        self._gpu_best_timeline.append(
            {
                "ts": time.time(),
                "difficulty": float(difficulty),
                "hash_fp": _fp(hash_be_hex) if hash_be_hex else "",
            }
        )

    def on_accepted_best(self, difficulty: float, hash_be_hex: str = "") -> None:
        self._acc_best_timeline.append(
            {
                "ts": time.time(),
                "difficulty": float(difficulty),
                "hash_fp": _fp(hash_be_hex) if hash_be_hex else "",
            }
        )

    def _unique_and_dup(self) -> tuple[int, int]:
        # _coverage stores already-merged intervals per (family, en2);
        # duplicates are recovered as total_attempts - unique_coverage.
        unique = 0
        for ivals in self._coverage.values():
            unique += coverage_unique_len(ivals)
        dup = max(0, int(self._total_attempts) - int(unique))
        return int(unique), int(dup)

    def _hashrate_stats(self) -> dict[str, Any]:
        vals = [float(s["hashrate"]) for s in self._hashrate_samples if s.get("hashrate")]
        if not vals:
            return {
                "hashrate_sample_count": 0,
                "hashrate_mean": 0.0,
                "hashrate_min": 0.0,
                "hashrate_max": 0.0,
            }
        return {
            "hashrate_sample_count": len(vals),
            "hashrate_mean": sum(vals) / len(vals),
            "hashrate_min": min(vals),
            "hashrate_max": max(vals),
        }

    def metrics(self) -> dict[str, Any]:
        unique, dup = self._unique_and_dup()
        total = int(self._total_attempts)
        rate = (100.0 * dup / total) if total > 0 else 0.0
        now = time.time()
        job_summaries = []
        for st in self._jobs.values():
            end = st.ended_ts if st.ended_ts is not None else (
                now if st.job_id == self._current_job_id else st.started_ts
            )
            job_summaries.append(
                {
                    "job_id": st.job_id,
                    "family_id": st.family_id,
                    "clean": st.clean,
                    "hashes_scanned": st.hashes_scanned,
                    "batches_completed": st.batches_completed,
                    "duration_s": max(0.0, end - st.started_ts),
                    "cut_by_notify": st.cut_by_notify,
                    "cut_reason": st.cut_reason,
                }
            )
        overhead_ms = self._overhead_s_total * 1000.0
        kernel_ms = self._kernel_s_total * 1000.0
        overhead_pct = (100.0 * self._overhead_s_total / self._kernel_s_total) if self._kernel_s_total > 0 else 0.0
        is_gpu = self.measurement_source == MEASUREMENT_GPU
        return {
            "measurement_source": self.measurement_source,
            "attempts_are_gpu_completed": bool(is_gpu),
            "attempts_are_synthetic": not is_gpu,
            "total_attempts": total,
            # Unique/dup derived from completed intervals (not a time-budget estimate)
            "unique_attempts": int(unique),
            "estimated_unique_attempts": int(unique),  # UI alias; same as unique_attempts
            "duplicate_attempts": int(dup),
            "duplicate_rate_percent": float(rate),
            "identical_work_notifications": int(self._identical_work_notifications),
            "reconnects": int(self._reconnects),
            "extranonce1_changes": int(self._en1_changes),
            "aborted_inflight_batches": int(self._aborted_inflight),
            "jobs_cut_by_notify": int(self._jobs_cut_by_notify),
            "hashes_completed_on_cut_jobs": int(self._hashes_on_cut_jobs),
            "batches_completed": int(self._batches_completed),
            "jobs_seen": len(self._jobs),
            "notify_count": len(self._notify_events),
            "ledger_overhead_ms_total": float(overhead_ms),
            "ledger_overhead_calls": int(self._overhead_calls),
            "ledger_overhead_pct_of_kernel": float(overhead_pct),
            "kernel_ms_observed": float(kernel_ms),
            "gpu_best_timeline": list(self._gpu_best_timeline),
            "accepted_best_timeline": list(self._acc_best_timeline),
            "job_summaries": job_summaries,
            **self._hashrate_stats(),
            "uptime_s": max(0.0, now - self._created_ts),
        }

    def export_dict(self, *, mask: bool = True) -> dict[str, Any]:
        m = self.metrics()
        return {
            **m,
            "notify_events": [dict(ev) for ev in self._notify_events],
            "subscribe_events": self._subscribe_events_export(mask=mask),
            "masked": bool(mask),
            "disclaimer": (
                "total_attempts / duplicate_* are from completed GPU batches "
                "(result.scanned) when measurement_source=gpu_completed_batches. "
                "Synthetic time-budget sessions must use measurement_source="
                "synthetic_time_budget_not_gpu and must not be treated as GPU proof."
                if self.measurement_source == MEASUREMENT_GPU
                else "SYNTHETIC session — NOT a real GPU mining measurement. "
                "Do not treat total_attempts as GPU ATTEMPTS."
            ),
        }

    def _subscribe_events_export(self, *, mask: bool) -> list[dict[str, Any]]:
        out = []
        for s in self._subscribe_events:
            row = {
                "ts": s["ts"],
                "session_id": s["session_id"],
                "extranonce2_size": s["extranonce2_size"],
                "extranonce1_fp": s["extranonce1_fp"],
            }
            if not mask and "extranonce1_raw" in s:
                row["extranonce1"] = s["extranonce1_raw"]
            out.append(row)
        return out
