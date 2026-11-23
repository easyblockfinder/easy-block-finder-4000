"""Float-safe vertical pan ↔ y_bias folding for the mega-map shaft."""

from __future__ import annotations


def fold_pan_y_into_bias(
    pan_y: float, y_bias: int, cs: float, limit: float
) -> tuple[float, int]:
    """Absorb extreme pan.y into y_bias; preserve wy = bias + (sy - pan_y) / cs."""
    if cs <= 0:
        return pan_y, int(y_bias)
    bias = int(y_bias)
    # Large positive pan → shallower relative rows → decrease bias.
    if pan_y > limit:
        k = int((pan_y - limit) / cs) + 1
        k_apply = min(k, max(0, bias))
        bias -= k_apply
        pan_y -= k_apply * cs
    # Large negative pan → deeper rows → increase bias.
    if pan_y < -limit:
        k = int((-limit - pan_y) / cs) + 1
        bias += k
        pan_y += k * cs
    return pan_y, bias
