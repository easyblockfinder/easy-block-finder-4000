"""
Offline Engine Audit — no pool, no AppData record/lifetime writes.

Runs synthetic header scans through GpuMiner.search_audit and optionally
compares wall time to production search() for measured overhead.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from audit.histogram import SessionHistogram
from audit.stats import evaluate_disjoint_bands, evaluate_focus_cumulative
from audit.thresholds import AUDIT_DIFFICULTY_THRESHOLDS
from gpu.miner import GpuMiner, GpuUnavailableError
from mining.bitcoin import midstate_from_header


# Fixed synthetic header family (genesis) — deterministic across runs.
_OFFLINE_HEADER = bytes.fromhex(
    "0100000000000000000000000000000000000000000000000000000000000000"
    "000000003ba3edfd7a7b12b27ac72c3e67768f617fc81bc3888a51323a9fb8aa"
    "4b1e5e4a29ab5f49ffff001d1dac2b7c"
)
_IMPOSSIBLE_SHARE = 1


@dataclass
class OfflineAuditReport:
    status: str  # ok | skipped | error
    device_name: str = ""
    attempts: int = 0
    unique_attempts: int = 0
    histogram_counts: list[int] = field(default_factory=list)
    histogram_overflow: bool = False
    best_difficulty: float | None = None
    best_nonce: int | None = None
    cpu_verify_failures: int = 0
    duplicate_ranges: int = 0
    extranonce_wraps: int = 0
    band_evals: list[dict[str, Any]] = field(default_factory=list)
    focus_evals: list[dict[str, Any]] = field(default_factory=list)
    audit_kernel_s: float | None = None
    production_kernel_s: float | None = None
    overhead_percent: float | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_offline_engine_audit(
    *,
    total_hashes: int = 65536,
    batch_size: int = 8192,
    measure_overhead: bool = True,
    prefer_bus_id: Optional[str] = None,
) -> OfflineAuditReport:
    """
    Pure offline audit. Must not open sockets or touch best_hash / lifetime stores.
    """
    if total_hashes <= 0:
        return OfflineAuditReport(status="error", message="total_hashes must be > 0")

    try:
        gpu = GpuMiner(autotune_local=False, prefer_bus_id=prefer_bus_id)
    except GpuUnavailableError as exc:
        return OfflineAuditReport(
            status="skipped",
            message=f"OpenCL GPU unavailable (untested): {exc}",
        )

    try:
        if not gpu.ensure_audit_kernel():
            return OfflineAuditReport(
                status="skipped",
                device_name=gpu.device_name,
                message=f"Audit kernel unavailable (untested): {gpu._audit_error}",
            )

        ms = midstate_from_header(_OFFLINE_HEADER)
        session = SessionHistogram()
        seen_ranges: set[tuple[int, int]] = set()
        duplicate_ranges = 0
        best_diff: float | None = None
        best_nonce: int | None = None
        cpu_fail = 0
        audit_s = 0.0
        start = 0
        remaining = int(total_hashes)

        while remaining > 0:
            take = min(int(batch_size), remaining)
            key = (start, take)
            if key in seen_ranges:
                duplicate_ranges += 1
            seen_ranges.add(key)

            t0 = time.perf_counter()
            result, hist = gpu.search_audit(
                ms,
                _OFFLINE_HEADER,
                _IMPOSSIBLE_SHARE,
                start,
                take,
                track_best=True,
            )
            audit_s += time.perf_counter() - t0
            session.add(hist)

            if result.best_hash_be is not None and result.best_nonce is not None:
                from mining.best_hash import (
                    difficulty_from_hash_int,
                    hash_digest_be_to_int,
                    verify_best_candidate,
                )

                # best_hash_be is raw digest; verify uses explorer hex
                hx = result.best_hash_be_hex
                assert hx is not None
                hdr = _OFFLINE_HEADER[:76] + (result.best_nonce & 0xFFFFFFFF).to_bytes(
                    4, "little"
                )
                if not verify_best_candidate(hdr, hx):
                    cpu_fail += 1
                else:
                    dval = difficulty_from_hash_int(hash_digest_be_to_int(result.best_hash_be[::-1]))
                    if best_diff is None or dval > best_diff:
                        best_diff = dval
                        best_nonce = int(result.best_nonce)

            start = (start + take) & 0xFFFFFFFF
            remaining -= take

        prod_s: float | None = None
        overhead: float | None = None
        if measure_overhead and total_hashes >= batch_size:
            # Same work volume on production kernel (no hist)
            n_meas = min(total_hashes, batch_size * 4)
            t0 = time.perf_counter()
            off = 0
            left = n_meas
            while left > 0:
                take = min(batch_size, left)
                gpu.search(ms, _OFFLINE_HEADER, _IMPOSSIBLE_SHARE, off, take, track_best=True)
                off = (off + take) & 0xFFFFFFFF
                left -= take
            prod_s = time.perf_counter() - t0
            # Scale audit time to same hash count for fair %
            audit_scaled = audit_s * (n_meas / max(1, session.attempts))
            if prod_s > 0:
                overhead = (audit_scaled - prod_s) / prod_s * 100.0

        bands = evaluate_disjoint_bands(session.attempts, session.counts)
        focus = evaluate_focus_cumulative(session.attempts, session.counts)

        return OfflineAuditReport(
            status="ok",
            device_name=gpu.device_name,
            attempts=session.attempts,
            unique_attempts=session.attempts - 0,  # offline synthetic: no family dup
            histogram_counts=list(session.counts),
            histogram_overflow=session.overflow,
            best_difficulty=best_diff,
            best_nonce=best_nonce,
            cpu_verify_failures=cpu_fail,
            duplicate_ranges=duplicate_ranges,
            extranonce_wraps=0,
            band_evals=[asdict(b) for b in bands],
            focus_evals=[asdict(b) for b in focus],
            audit_kernel_s=audit_s,
            production_kernel_s=prod_s,
            overhead_percent=overhead,
            message=(
                f"Offline audit complete: N={session.attempts:,} "
                f"thresholds={list(AUDIT_DIFFICULTY_THRESHOLDS)}"
            ),
        )
    except Exception as exc:
        return OfflineAuditReport(
            status="error",
            device_name=getattr(gpu, "device_name", ""),
            message=str(exc),
        )
    finally:
        try:
            gpu.close()
        except Exception:
            pass
