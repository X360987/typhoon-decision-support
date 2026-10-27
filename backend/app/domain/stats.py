"""Rolling baseline helpers. Never use future values."""

from __future__ import annotations

import math
from typing import Sequence


def median(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return None
    vals = sorted(vals)
    n = len(vals)
    mid = n // 2
    if n % 2:
        return vals[mid]
    return (vals[mid - 1] + vals[mid]) / 2.0


def mad(values: Sequence[float]) -> float | None:
    med = median(values)
    if med is None:
        return None
    deviations = [abs(v - med) for v in values if v is not None]
    return median(deviations)


def robust_z(value: float | None, history: Sequence[float]) -> tuple[float | None, str]:
    """Return (z, status). status may be ok|insufficient|mad_zero."""
    hist = [v for v in history if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if value is None or len(hist) < 3:
        return None, "insufficient"
    med = median(hist)
    m = mad(hist)
    if med is None:
        return None, "insufficient"
    if m is None or m == 0:
        # fallback: compare to median with absolute gap using std-like eps
        if value == med:
            return 0.0, "mad_zero"
        return None, "mad_zero"
    z = 0.6745 * (value - med) / m
    return z, "ok"


def quantile(values: Sequence[float], q: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if q <= 0:
        return vals[0]
    if q >= 1:
        return vals[-1]
    idx = q * (len(vals) - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return vals[lo]
    w = idx - lo
    return vals[lo] * (1 - w) + vals[hi] * w


def rolling_mean(history: Sequence[float]) -> float | None:
    vals = [v for v in history if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Missing is not zero. Zero denominator yields None."""
    if numerator is None or denominator is None:
        return None
    if denominator == 0:
        return None
    return numerator / denominator
