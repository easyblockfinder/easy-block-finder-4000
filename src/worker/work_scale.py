"""Native intensity ladder + adaptive auto-idle duty-cycle sleep.

When auto-idle is OFF or scale==1.0, behavior matches the historical
(intensity → batch, base_sleep) ladder exactly.

When 0 < scale < 1, post-batch wait uses measured batch time T and base sleep B:

    sleep = max(0, ((T + B) / S) - T)

Base sleep is not applied twice. Batch size stays at the user's intensity
ceiling so duty-cycle tracks that intensity's work unit.
"""

from __future__ import annotations

_INTENSITY_LADDER: dict[int, tuple[int, float]] = {
    1: (1_048_576, 0.008),
    2: (1_048_576, 0.005),
    3: (2_097_152, 0.004),
    4: (2_097_152, 0.002),
    5: (4_194_304, 0.002),
    6: (4_194_304, 0.001),
    7: (8_388_608, 0.001),
    8: (8_388_608, 0.0),
    9: (16_777_216, 0.0),
    10: (33_554_432, 0.0),
}


def clamp_intensity(level: int) -> int:
    return max(1, min(10, int(level)))


def clamp_scale(scale: float) -> float:
    try:
        s = float(scale)
    except (TypeError, ValueError):
        return 1.0
    if s < 0.0:
        return 0.0
    if s > 1.0:
        return 1.0
    return s


def intensity_batch_sleep(base_intensity: int) -> tuple[int, float]:
    """Historical intensity ladder entry (batch, base_sleep B)."""
    level = clamp_intensity(base_intensity)
    batch, base_sleep = _INTENSITY_LADDER[level]
    return int(batch), float(base_sleep)


def adaptive_duty_sleep(batch_time_s: float, base_sleep_s: float, scale: float) -> float:
    """
    Post-batch wait for scale S in (0, 1].

    sleep = max(0, ((T + B) / S) - T)

    S >= 1 → returns B (same as legacy inter-batch sleep; T unused for wait).
    S <= 0 → returns 0 (caller must pause scanning entirely).
    """
    s = clamp_scale(scale)
    b = max(0.0, float(base_sleep_s))
    t = max(0.0, float(batch_time_s))
    if s <= 0.0:
        return 0.0
    if s >= 1.0:
        return b
    return max(0.0, ((t + b) / s) - t)


def update_ema(previous: float | None, sample: float, *, alpha: float = 0.3) -> float:
    """Light EMA for batch-time smoothing; alpha in (0, 1]."""
    a = min(1.0, max(0.05, float(alpha)))
    x = max(0.0, float(sample))
    if previous is None:
        return x
    return a * x + (1.0 - a) * float(previous)


# Back-compat name used by older tests — full scale only (no shrink).
def scaled_batch_sleep(base_intensity: int, scale: float) -> tuple[int, float]:
    """
    Deprecated path for tests: at S>=1 return ladder; at S<=0 return (0,0);
    at partial S return full batch + placeholder sleep (real adaptive uses
    adaptive_duty_sleep after measuring T).
    """
    batch, base_sleep = intensity_batch_sleep(base_intensity)
    s = clamp_scale(scale)
    if s <= 0.0:
        return 0, 0.0
    if s >= 1.0:
        return batch, base_sleep
    # Without T, approximate with T=0 → sleep = B/S (not used by controller).
    return batch, adaptive_duty_sleep(0.0, base_sleep, s)
