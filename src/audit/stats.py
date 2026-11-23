"""Observed vs expected threshold stats (nested cumulatives → disjoint bands)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from audit.thresholds import AUDIT_DIFFICULTY_THRESHOLDS

# Bitcoin DIFF1 convention: P(hash meets difficulty D) ≈ 1 / (2**32 * D)
POW32 = float(2**32)
DEFAULT_E_MIN = 5.0


@dataclass(frozen=True)
class BandEval:
    label: str
    d_lo: float
    d_hi: float | None  # None = +inf
    observed: int
    expected: float
    status: str  # ok | insufficient_sample | high | low
    note: str = ""


def expected_cumulative(n: int, difficulty: float) -> float:
    if n < 0 or difficulty <= 0:
        raise ValueError("n>=0 and difficulty>0 required")
    return float(n) / (POW32 * float(difficulty))


def expected_band(n: int, d_lo: float, d_hi: float | None) -> float:
    """Hashes with difficulty in [d_lo, d_hi) i.e. target(d_hi) < hash <= target(d_lo)."""
    e_lo = expected_cumulative(n, d_lo)
    if d_hi is None:
        return e_lo
    e_hi = expected_cumulative(n, d_hi)
    return max(0.0, e_lo - e_hi)


def poisson_pvalue_two_sided(observed: int, expected: float) -> float:
    """Exact Poisson two-sided p via denser-tail sum; expected must be > 0."""
    if expected <= 0:
        return 1.0
    # P(X=k) = e^{-λ} λ^k / k!
    # Two-sided: sum probs of outcomes with P(X=x) <= P(X=obs)
    log_p0 = -expected
    probs: list[float] = []
    # Bound: accumulate until far into tail
    max_k = max(observed * 2 + 50, int(expected + 20 * math.sqrt(expected)) + 10)
    log_pk = log_p0
    for k in range(0, max_k + 1):
        probs.append(math.exp(log_pk))
        log_pk += math.log(expected) - math.log(k + 1)
    p_obs = probs[observed] if observed < len(probs) else 0.0
    return min(1.0, sum(p for p in probs if p <= p_obs + 1e-18))


def evaluate_disjoint_bands(
    n: int,
    cumulative_counts: Sequence[int],
    thresholds: Sequence[float] = AUDIT_DIFFICULTY_THRESHOLDS,
    e_min: float = DEFAULT_E_MIN,
) -> list[BandEval]:
    """
    Convert nested cumulative counts into disjoint bands and score each.
    cumulative_counts[i] = #hashes meeting difficulty >= thresholds[i].
    """
    if len(cumulative_counts) != len(thresholds):
        raise ValueError("counts/thresholds length mismatch")
    # Highest band: >= max threshold
    bands: list[BandEval] = []
    th = list(thresholds)
    # band i: [th[i], th[i+1]) for i < n-1; last: [th[-1], +inf)
    for i, d_lo in enumerate(th):
        d_hi = th[i + 1] if i + 1 < len(th) else None
        c_lo = int(cumulative_counts[i])
        c_hi = int(cumulative_counts[i + 1]) if d_hi is not None else 0
        obs = c_lo - c_hi
        if obs < 0:
            # Should not happen if targets monotonic; clamp + flag
            bands.append(
                BandEval(
                    label=f"[{d_lo}, {d_hi or '∞'})",
                    d_lo=d_lo,
                    d_hi=d_hi,
                    observed=obs,
                    expected=expected_band(n, d_lo, d_hi),
                    status="invalid",
                    note="cumulative non-monotonic",
                )
            )
            continue
        exp = expected_band(n, d_lo, d_hi)
        if exp < e_min:
            status = "insufficient_sample"
            note = f"E={exp:.3g} < E_min={e_min}"
        else:
            p = poisson_pvalue_two_sided(obs, exp)
            if p < 0.01 and obs > exp * 2:
                status = "high"
            elif p < 0.01 and obs < exp * 0.5:
                status = "low"
            else:
                status = "ok"
            note = f"p≈{p:.3g}"
        bands.append(
            BandEval(
                label=f"[{d_lo}, {d_hi if d_hi is not None else '∞'})",
                d_lo=d_lo,
                d_hi=d_hi,
                observed=obs,
                expected=exp,
                status=status,
                note=note,
            )
        )
    return bands


def evaluate_focus_cumulative(
    n: int,
    cumulative_counts: Sequence[int],
    thresholds: Sequence[float] = AUDIT_DIFFICULTY_THRESHOLDS,
    focus: Sequence[float] = (4200.0, 5000.0, 10000.0),
    e_min: float = DEFAULT_E_MIN,
) -> list[BandEval]:
    """Pre-registered cumulative checks (dependent — report, don't treat as independent)."""
    out: list[BandEval] = []
    for d in focus:
        try:
            i = list(thresholds).index(float(d))
        except ValueError:
            continue
        obs = int(cumulative_counts[i])
        exp = expected_cumulative(n, float(d))
        if exp < e_min:
            status, note = "insufficient_sample", f"E={exp:.3g} < E_min={e_min}"
        else:
            p = poisson_pvalue_two_sided(obs, exp)
            status = "ok" if p >= 0.01 else ("high" if obs > exp else "low")
            note = f"p≈{p:.3g} (cumulative; nested — not independent of other D)"
        out.append(
            BandEval(
                label=f">= {d}",
                d_lo=float(d),
                d_hi=None,
                observed=obs,
                expected=exp,
                status=status,
                note=note,
            )
        )
    return out
