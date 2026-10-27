"""Prediction features, baselines, and leakage-safe labeling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Sequence

import numpy as np


@dataclass
class PredSample:
    event_id: int
    province_code: str
    origin_time: datetime
    lead_hours: int
    features: dict[str, float]
    label: float | None
    label_available: bool


def clip_prediction(value: float | None, clip_min: float | None, clip_max: float | None) -> float | None:
    if value is None:
        return None
    v = value
    if clip_min is not None:
        v = max(clip_min, v)
    if clip_max is not None:
        v = min(clip_max, v)
    return v


def naive_baseline(history: Sequence[float | None]) -> float | None:
    """Mean of the six most recent known hours. ``history`` is newest first: origin-1h, origin-2h, ..."""
    vals = [v for v in history if v is not None]
    if not vals:
        return None
    return float(np.mean(vals[:6]))


def ratio_baseline(history: Sequence[float | None]) -> float | None:
    """Mean of up to twelve most recent known hours; ``history`` is newest first."""
    vals = [v for v in history if v is not None]
    if not vals:
        return None
    return float(np.mean(vals[:12]))


def build_lag_features(
    series: dict[datetime, float | None],
    origin: datetime,
    lags: Sequence[int] = (1, 3, 6, 12),
) -> dict[str, float]:
    """Only use values strictly before or at origin (known at origin)."""
    feats: dict[str, float] = {}
    for lag in lags:
        t = origin - timedelta(hours=lag)
        v = series.get(t)
        feats[f"lag_{lag}"] = float(v) if v is not None else 0.0
        feats[f"lag_{lag}_missing"] = 0.0 if v is not None else 1.0
    hist = [series.get(origin - timedelta(hours=i)) for i in range(1, 13)]
    known = [h for h in hist if h is not None]
    feats["roll_mean_12"] = float(np.mean(known)) if known else 0.0
    feats["roll_std_12"] = float(np.std(known)) if len(known) > 1 else 0.0
    feats["hour_of_day"] = float(origin.hour)
    feats["known_count"] = float(len(known))
    return feats


def select_forecast_features(
    forecast_points: list[dict[str, Any]],
    origin: datetime,
    province_code: str,
    lead_hours: int = 3,
    tolerance_hours: int = 3,
) -> dict[str, float]:
    """Latest forecast issued and arrived by ``origin`` whose valid_time is closest to origin+lead.

    A point applies to a province when it names that province; points without a
    province are event-wide (e.g. track points) and apply to every province.
    """
    feats = {"forecast_wind": 0.0, "forecast_available": 0.0, "path_distance_proxy": 0.0}
    target = origin + timedelta(hours=lead_hours)
    tol = timedelta(hours=tolerance_hours)
    usable = [
        f
        for f in forecast_points
        if f.get("issued_at") is not None
        and f.get("arrived_at") is not None
        and f["issued_at"] <= origin
        and f["arrived_at"] <= origin
        and f.get("province_code") in (None, province_code)
        and f.get("valid_time") is not None
        and abs(f["valid_time"] - target) <= tol
    ]
    if not usable:
        return feats
    usable.sort(key=lambda x: (x["issued_at"], -abs((x["valid_time"] - target).total_seconds())), reverse=True)
    top = usable[0]
    if top.get("metric") == "max_wind" and top.get("value") is not None:
        feats["forecast_wind"] = float(top["value"])
        feats["forecast_available"] = 1.0
    if top.get("path_distance_proxy") is not None:
        feats["path_distance_proxy"] = float(top["path_distance_proxy"])
        feats["forecast_available"] = 1.0
    return feats


FEATURE_CONTRACT_VERSION = "features-v2"
LAG_HOURS = (1, 3, 6, 12)
FEATURE_NAMES: tuple[str, ...] = (
    *(f"lag_{lag}" for lag in LAG_HOURS),
    *(f"lag_{lag}_missing" for lag in LAG_HOURS),
    "roll_mean_12",
    "roll_std_12",
    "hour_of_day",
    "known_count",
    "forecast_wind",
    "forecast_available",
    "path_distance_proxy",
)


def feature_contract() -> dict[str, Any]:
    return {
        "version": FEATURE_CONTRACT_VERSION,
        "names": list(FEATURE_NAMES),
        "missing": "lag value 0 with lag_k_missing=1; forecast fields 0 with forecast_available=0",
        "lags": list(LAG_HOURS),
    }


def build_feature_vector(
    series: dict[datetime, float | None],
    origin: datetime,
    forecast_points: list[dict[str, Any]],
    province_code: str,
    lead_hours: int,
) -> list[float]:
    """Single feature builder shared by training and inference, ordered by FEATURE_NAMES."""
    feats = build_lag_features(series, origin, LAG_HOURS)
    feats.update(select_forecast_features(forecast_points, origin, province_code, lead_hours))
    return [float(feats[name]) for name in FEATURE_NAMES]


def mae(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    a = np.asarray(y_true, dtype=float)
    b = np.asarray(y_pred, dtype=float)
    return float(np.mean(np.abs(a - b))) if len(a) else float("nan")


def rmse(y_true: Sequence[float], y_pred: Sequence[float]) -> float:
    a = np.asarray(y_true, dtype=float)
    b = np.asarray(y_pred, dtype=float)
    return float(np.sqrt(np.mean((a - b) ** 2))) if len(a) else float("nan")


def future_window_sum(
    series: dict[datetime, float | None], origin: datetime, window_hours: int
) -> float | None:
    """Label for cumulative targets: sum of (origin, origin+window]. Missing any hour -> None if strict."""
    total = 0.0
    known = 0
    for h in range(1, window_hours + 1):
        v = series.get(origin + timedelta(hours=h))
        if v is None:
            continue
        total += v
        known += 1
    if known == 0:
        return None
    return total
