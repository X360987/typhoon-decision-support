"""场景：灾中。维度之间最多 6 小时的领先滞后、耦合强度和状态。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any


def _corr(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    dx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    dy = math.sqrt(sum((b - my) ** 2 for b in ys))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def lead_lag(series_a: dict[datetime, float], series_b: dict[datetime, float], max_lag_hours: int = 6) -> dict[str, Any]:
    """Positive lag means series_b follows series_a."""
    hours = sorted(set(series_a) | set(series_b))
    best: tuple[float, int, int] | None = None
    for lag in range(-max_lag_hours, max_lag_hours + 1):
        xs: list[float] = []
        ys: list[float] = []
        for hour in hours:
            other = hour + timedelta(hours=lag)
            if hour in series_a and other in series_b:
                xs.append(series_a[hour])
                ys.append(series_b[other])
        score = _corr(xs, ys)
        if score is None:
            continue
        if best is None or abs(score) > abs(best[0]):
            best = (score, lag, len(xs))
    if best is None:
        return {
            "lead_lag_hours": None,
            "strength": None,
            "contribution": None,
            "state": "insufficient",
            "sample_size": 0,
        }
    score, lag, size = best
    strength = abs(score)
    if strength < 0.35:
        state = "imbalance"
    elif lag == 0:
        state = "sync"
    else:
        state = "lag"
    return {
        "lead_lag_hours": lag,
        "strength": strength,
        "contribution": score,
        "state": state,
        "sample_size": size,
    }


def couple_dimensions(
    series: dict[str, dict[datetime, float]],
    max_lag_hours: int = 6,
) -> list[dict[str, Any]]:
    names = [name for name in ("social", "organizational", "physical") if name in series]
    pairs = []
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            result = lead_lag(series[left], series[right], max_lag_hours)
            pairs.append({"pair": [left, right], **result})
    return pairs
