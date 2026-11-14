"""Hashrate window — batch start/end times and actual H/s."""

from __future__ import annotations


def rate_from_window(
    window: list[tuple[float, float, int]],
    *,
    now: float | None = None,
    last_kernel_s: float = 0.0,
) -> float:
    """
    window: (t_start, t_end, scanned_hashes) — monotonic/perf_counter times.
    Rate = total_hash / (last_end - first_start); includes idle gaps between batches.

    Example: 0-1s 1e6 hash, 1-2s 1e6 hash -> 2e6 / 2s = 1e6 H/s.
    """
    del now  # API compatibility comes from in-span log timestamps
    if not window:
        return 0.0
    total = sum(int(n) for _, _, n in window)
    if total <= 0:
        return 0.0
    t0 = float(window[0][0])
    t1 = float(window[-1][1])
    span = t1 - t0
    if span > 0:
        return total / span
    if len(window) == 1 and last_kernel_s > 0:
        return float(window[0][2]) / last_kernel_s
    return 0.0


def rate_kernel_only(
    scanned: int,
    kernel_s: float,
) -> float:
    """Kernel time only (no idle gaps) — label separately in the UI."""
    if scanned <= 0 or kernel_s <= 0:
        return 0.0
    return float(scanned) / float(kernel_s)
