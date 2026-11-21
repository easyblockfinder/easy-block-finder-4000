"""Map user intensity (1–10) × auto-idle scale (0..1) → batch size + inter-batch sleep."""

from __future__ import annotations

# Same ladder as MiningController._INTENSITY (batch, sleep_s).
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

_MIN_BATCH = 65_536


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


def scaled_batch_sleep(base_intensity: int, scale: float) -> tuple[int, float]:
    """
    Fine-grained work scaling under the user's intensity ceiling.

    scale=1.0 → exact ladder entry for base_intensity.
    scale=0.0 → caller should pause (batch unused); returns (0, 0.0).
    Intermediate: shrink batch toward a floor and stretch sleep so effective
    throughput tracks scale without only snapping to integer intensity steps.
    """
    level = clamp_intensity(base_intensity)
    s = clamp_scale(scale)
    base_batch, base_sleep = _INTENSITY_LADDER[level]
    if s <= 0.0:
        return 0, 0.0
    if s >= 1.0:
        return int(base_batch), float(base_sleep)

    # Batch: linear in scale, floored so OpenCL still gets useful work.
    batch = int(round(base_batch * s))
    batch = max(_MIN_BATCH, min(base_batch, batch))

    # Sleep: at full scale use ladder sleep; as scale drops, add extra idle time
    # approximating (1/s - 1) * kernel_budget. Use base_sleep as minimum.
    # Effective duty ≈ s when base_sleep==0 by injecting sleep proportional to
    # missing capacity (assume ~kernel slot ~ batch-relative constant).
    if base_sleep <= 0.0:
        # Invent a small reference period so %10 is meaningfully quieter.
        ref = 0.002
        sleep_s = ref * (1.0 / s - 1.0)
    else:
        sleep_s = base_sleep / s
    # Cap pathological sleeps
    sleep_s = min(2.0, max(0.0, float(sleep_s)))
    return batch, sleep_s
