from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
from sqlalchemy.orm import Session

from app.config import get_settings
from app.domain.prediction import (
    FEATURE_CONTRACT_VERSION,
    build_feature_vector,
    clip_prediction,
    feature_contract,
    mae,
    naive_baseline,
    ratio_baseline,
    rmse,
)
from app.models import (
    DataReadinessReport,
    EvaluationResult,
    ForecastPoint,
    ForecastSnapshot,
    ModelRegistry,
    PredictionResult,
    PredictionRun,
    ProvinceHourMetric,
)
from app.services.pipeline import NATIONAL, get_active_version
from app.services.rules_loader import load_prediction_targets

TARGET_METRIC = {
    "affected_trains": "affected_trains",
    "personal_weibo_count": "personal_weibo_count",
    "negative_ratio": "negative_ratio",
    "official_weibo_count": "official_weibo_count",
}
ML_HORIZON = 3
INTERVAL_UNAVAILABLE = "区间不可用：当前模型与基线均不输出经过校准的预测区间"


def build_readiness_report(db: Session, dataset_id: str) -> dict[str, Any]:
    from app.models import Event, SuspensionRegionHour, WeiboClean

    events = db.query(Event).filter(Event.dataset_id == dataset_id).all()
    active = {e.id: get_active_version(db, dataset_id, e.id) for e in events}
    metrics = [
        m
        for m in db.query(ProvinceHourMetric).filter(
            ProvinceHourMetric.dataset_id == dataset_id, ProvinceHourMetric.province_code != NATIONAL
        )
        if active.get(m.event_id) == m.version
    ]
    forecasts = db.query(ForecastSnapshot).filter(ForecastSnapshot.dataset_id == dataset_id).count()
    personal = (
        db.query(WeiboClean).filter(WeiboClean.dataset_id == dataset_id, WeiboClean.account_class == "personal").count()
    )
    official = (
        db.query(WeiboClean).filter(WeiboClean.dataset_id == dataset_id, WeiboClean.account_class == "official").count()
    )
    unknown = (
        db.query(WeiboClean).filter(WeiboClean.dataset_id == dataset_id, WeiboClean.account_class == "unknown").count()
    )
    sus = db.query(SuspensionRegionHour).filter(SuspensionRegionHour.dataset_id == dataset_id).count()

    by_metric: dict[str, list] = {}
    for m in metrics:
        by_metric.setdefault(m.metric_id, []).append(m)

    targets_cfg = load_prediction_targets()
    gate = targets_cfg.get("training_gate", {})
    target_reports = []
    for t in targets_cfg.get("targets", []):
        rows = by_metric.get(TARGET_METRIC.get(t["id"], t["id"]), [])
        known = [r.value for r in rows if r.value is not None]
        zero_ratio = (sum(1 for v in known if v == 0) / len(known)) if known else None
        missing_rate = 1 - (len(known) / len(rows)) if rows else 1.0
        reasons = []
        if len(events) < int(gate.get("min_events", 1)):
            reasons.append("insufficient_events")
        if len(rows) < int(gate.get("min_province_hours", 50)):
            reasons.append("insufficient_province_hours")
        if len(known) < int(gate.get("min_labels_per_target", 30)):
            reasons.append("insufficient_labels")
        target_reports.append(
            {
                "target_id": t["id"],
                "name": t["name"],
                "unit": t["unit"],
                "valid_labels": len(known),
                "missing_rate": missing_rate,
                "zero_ratio": zero_ratio,
                "gate_passed": not reasons,
                "gate_reason": "ok" if not reasons else ",".join(reasons),
            }
        )

    evaluations = db.query(EvaluationResult).filter(EvaluationResult.dataset_id == dataset_id).all()
    split_types = {str((e.split_info or {}).get("type")) for e in evaluations}
    report = {
        "dataset_id": dataset_id,
        "event_count": len(events),
        "time_span": {
            "start": min((e.start_time for e in events), default=None),
            "end": max((e.end_time for e in events), default=None),
        },
        "province_hour_rows": len(metrics),
        "personal_weibo": personal,
        "official_weibo": official,
        "unknown_account_weibo": unknown,
        "suspension_region_hours": sus,
        "forecast_snapshots": forecasts,
        "targets": target_reports,
        "cross_event_note": "仅有模拟/单案例时不可报告跨事件泛化效果",
        "delivery_stage": {
            "system_function": "按验收清单逐项核对，不由本报告自动认定",
            "single_event_experiment": any("within_event" in s for s in split_types),
            "cross_event_validation": any("cross_event" in s for s in split_types),
        },
    }
    for k in ("start", "end"):
        if report["time_span"][k]:
            report["time_span"][k] = report["time_span"][k].isoformat()
    db.add(DataReadinessReport(dataset_id=dataset_id, report=report))
    db.commit()
    return report


def _series_map(
    db: Session,
    dataset_id: str,
    event_id: int,
    province: str,
    metric_id: str,
    version: str,
    known_at: datetime | None = None,
) -> dict[datetime, float | None]:
    """Hourly series; with ``known_at`` only values whose availability is known and not later than it."""
    rows = (
        db.query(ProvinceHourMetric)
        .filter(
            ProvinceHourMetric.dataset_id == dataset_id,
            ProvinceHourMetric.event_id == event_id,
            ProvinceHourMetric.province_code == province,
            ProvinceHourMetric.metric_id == metric_id,
            ProvinceHourMetric.version == version,
        )
        .all()
    )
    out: dict[datetime, float | None] = {}
    for r in rows:
        if known_at is not None and (r.available_at is None or r.available_at > known_at):
            continue
        out[r.hour_bj] = r.value
    return out


def _forecast_dicts(db: Session, dataset_id: str, event_id: int) -> list[dict[str, Any]]:
    rows = (
        db.query(ForecastPoint, ForecastSnapshot)
        .join(ForecastSnapshot, ForecastSnapshot.id == ForecastPoint.snapshot_id)
        .filter(ForecastSnapshot.dataset_id == dataset_id, ForecastSnapshot.event_id == event_id)
        .all()
    )
    return [
        {
            "issued_at": s.issued_at,
            "arrived_at": s.arrived_at,
            "valid_time": p.valid_time,
            "lead_hours": p.lead_hours,
            "metric": p.metric,
            "value": p.value,
            "province_code": p.province_code,
            "path_distance_proxy": p.path_distance_proxy,
        }
        for p, s in rows
    ]


def _units(db: Session, dataset_id: str, event_id: int, version: str) -> list[str]:
    return sorted(
        {
            r.province_code
            for r in db.query(ProvinceHourMetric.province_code)
            .filter(
                ProvinceHourMetric.dataset_id == dataset_id,
                ProvinceHourMetric.event_id == event_id,
                ProvinceHourMetric.version == version,
            )
            .distinct()
        }
    )


def _load_model(data_mode: str, target_id: str, origin_time: datetime, db: Session):
    """Return (model, registry row, reason when refused)."""
    reg = db.query(ModelRegistry).filter(ModelRegistry.model_key == f"{data_mode}|{target_id}|{ML_HORIZON}").first()
    if reg is None or not reg.artifact_path or not Path(reg.artifact_path).exists():
        return None, None, "no_registered_model"
    contract = reg.feature_contract or {}
    if contract.get("version") != FEATURE_CONTRACT_VERSION or contract.get("names") != feature_contract()["names"]:
        return None, reg, "feature_contract_mismatch"
    cutoff_raw = (reg.train_window or {}).get("train_cutoff")
    if not cutoff_raw:
        return None, reg, "train_cutoff_unknown"
    if datetime.fromisoformat(cutoff_raw) > origin_time:
        return None, reg, "model_trained_after_origin"
    try:
        return joblib.load(reg.artifact_path), reg, None
    except Exception:  # noqa: BLE001
        return None, reg, "model_load_failed"


def run_predictions(
    db: Session,
    dataset_id: str,
    event_id: int,
    origin_time: datetime,
    data_mode: str = "demo",
) -> dict[str, Any]:
    cfg = load_prediction_targets()
    horizons = cfg.get("horizons_hours", [1, 3, 6, 12, 24])
    version = get_active_version(db, dataset_id, event_id)
    units = _units(db, dataset_id, event_id, version)
    run = PredictionRun(
        dataset_id=dataset_id,
        event_id=event_id,
        origin_time=origin_time,
        model_version="baseline-v1",
        status="running",
        quality_status="ok",
    )
    db.add(run)
    db.flush()

    forecast_pts = _forecast_dicts(db, dataset_id, event_id)
    results = 0
    model_versions: set[str] = set()
    for t in cfg.get("targets", []):
        mid = TARGET_METRIC[t["id"]]
        model, reg, refusal = _load_model(data_mode, t["id"], origin_time, db)
        model_cutoff = datetime.fromisoformat(reg.train_window["train_cutoff"]) if model is not None else None
        for unit in units:
            series = _series_map(db, dataset_id, event_id, unit, mid, version, known_at=origin_time)
            hist = [series.get(origin_time - timedelta(hours=i)) for i in range(1, 13)]
            base = ratio_baseline(hist) if t["id"] == "negative_ratio" else naive_baseline(hist)
            for lead in horizons:
                pred = base
                status = "baseline_prediction"
                mv = "baseline-v1"
                reason = None if lead == ML_HORIZON else f"仅 h{ML_HORIZON} 有树模型，其余提前量使用朴素基线"
                cutoff = None
                if lead == ML_HORIZON:
                    if model is not None:
                        x = np.array([build_feature_vector(series, origin_time, forecast_pts, unit, lead)])
                        try:
                            pred = float(model.predict(x)[0])
                            status = "demo_ml_prediction" if data_mode == "demo" else "ml_prediction"
                            mv = reg.version
                            cutoff = model_cutoff
                        except Exception:  # noqa: BLE001
                            reason = "tree_infer_failed_fallback_baseline"
                    else:
                        reason = refusal
                if pred is None:
                    status = "insufficient_data"
                    reason = "起点前无可用观测，基线与模型均不可用" + (f"；{reason}" if reason else "")
                pred = clip_prediction(pred, t.get("clip_min"), t.get("clip_max"))
                model_versions.add(mv)
                db.add(
                    PredictionResult(
                        run_id=run.id,
                        dataset_id=dataset_id,
                        event_id=event_id,
                        province_code=unit,
                        target_id=t["id"],
                        origin_time=origin_time,
                        valid_time=origin_time + timedelta(hours=lead),
                        lead_hours=lead,
                        point_pred=pred,
                        interval_low=None,
                        interval_high=None,
                        status=status,
                        reason=reason,
                        model_version=mv,
                        train_cutoff=cutoff,
                        data_version=version,
                        quality_status="ok" if pred is not None else "insufficient",
                    )
                )
                results += 1
    run.status = "completed"
    run.model_version = ",".join(sorted(model_versions)) or "baseline-v1"
    db.commit()
    return {"run_id": run.id, "results": results, "data_version": version}


def train_models(db: Session, dataset_id: str, event_id: int, data_mode: str = "demo") -> dict[str, Any]:
    """Single-event experiment with a global origin-time holdout. Not a cross-event validation."""
    settings = get_settings()
    Path(settings.artifact_dir).mkdir(parents=True, exist_ok=True)
    cfg = load_prediction_targets()
    gate = cfg.get("training_gate", {})
    version = get_active_version(db, dataset_id, event_id)
    forecast_pts = _forecast_dicts(db, dataset_id, event_id)
    units = _units(db, dataset_id, event_id, version)
    trained = []
    for t in cfg.get("targets", []):
        mid = TARGET_METRIC[t["id"]]
        baseline_fn = ratio_baseline if t["id"] == "negative_ratio" else naive_baseline
        samples: list[tuple[datetime, list[float], float, float | None]] = []
        for unit in units:
            full = _series_map(db, dataset_id, event_id, unit, mid, version)
            avail_rows = {
                r.hour_bj: r.available_at
                for r in db.query(ProvinceHourMetric).filter(
                    ProvinceHourMetric.dataset_id == dataset_id,
                    ProvinceHourMetric.event_id == event_id,
                    ProvinceHourMetric.province_code == unit,
                    ProvinceHourMetric.metric_id == mid,
                    ProvinceHourMetric.version == version,
                )
            }
            for origin in sorted(full):
                label = full.get(origin + timedelta(hours=ML_HORIZON))
                if label is None:
                    continue
                known = {h: v for h, v in full.items() if avail_rows.get(h) is not None and avail_rows[h] <= origin}
                base = baseline_fn([known.get(origin - timedelta(hours=i)) for i in range(1, 13)])
                samples.append(
                    (origin, build_feature_vector(known, origin, forecast_pts, unit, ML_HORIZON), label, base)
                )
        if len(samples) < int(gate.get("min_labels_per_target", 30)) or len(samples) < 40:
            trained.append({"target": t["id"], "status": "skipped_gate", "samples": len(samples)})
            continue
        origins = sorted({s[0] for s in samples})
        validation_start = origins[int(len(origins) * 0.7)]
        label_ready = timedelta(hours=ML_HORIZON + 1)
        train = [s for s in samples if s[0] + label_ready <= validation_start]
        test = [s for s in samples if s[0] >= validation_start]
        if len(train) < 20 or not test:
            trained.append({"target": t["id"], "status": "skipped_split", "train": len(train), "test": len(test)})
            continue
        train_cutoff = max(s[0] for s in train) + label_ready
        model = GradientBoostingRegressor(random_state=42)
        model.fit([s[1] for s in train], [s[2] for s in train])
        y_test = [s[2] for s in test]
        pred = model.predict([s[1] for s in test])
        with_base = [(s[2], s[3]) for s in test if s[3] is not None]
        metrics = {
            "mae": mae(y_test, pred),
            "rmse": rmse(y_test, pred),
            "baseline_mae": mae([y for y, _ in with_base], [b for _, b in with_base]) if with_base else None,
            "n_train": len(train),
            "n_test": len(test),
            "note": "单事件内全局时间留出（按 origin_time 切分），非跨事件验证",
        }
        path = Path(settings.artifact_dir) / f"{data_mode}_{t['id']}_h{ML_HORIZON}.joblib"
        joblib.dump(model, path)
        key = f"{data_mode}|{t['id']}|{ML_HORIZON}"
        train_window = {
            "split": "global_origin_time_holdout",
            "validation_start": validation_start.isoformat(),
            "train_cutoff": train_cutoff.isoformat(),
            "event_id": event_id,
            "data_version": version,
        }
        reg = db.query(ModelRegistry).filter(ModelRegistry.model_key == key).first()
        if reg is None:
            reg = ModelRegistry(model_key=key, target_id=t["id"], horizon_hours=ML_HORIZON, data_mode=data_mode)
            db.add(reg)
        reg.model_kind = "demo" if data_mode == "demo" else "tree"
        reg.feature_contract = feature_contract()
        reg.train_window = train_window
        reg.metrics = metrics
        reg.artifact_path = str(path)
        reg.version = f"{data_mode}-tree-{t['id']}-h{ML_HORIZON}-{version}"
        db.add(
            EvaluationResult(
                dataset_id=dataset_id,
                event_id=event_id,
                target_id=t["id"],
                horizon_hours=ML_HORIZON,
                split_info={"type": "within_event_global_time_holdout", **train_window},
                metrics=metrics,
                notes="填充/模拟数据实验；跨事件能力未验证" if data_mode == "demo" else "单事件实验；跨事件能力未验证",
            )
        )
        trained.append({"target": t["id"], "status": "trained", "metrics": metrics, "train_cutoff": train_cutoff.isoformat()})
    db.commit()
    return {"trained": trained, "cross_event_validated": False}


def train_demo_models(db: Session, dataset_id: str, event_id: int) -> dict[str, Any]:
    return train_models(db, dataset_id, event_id, data_mode="demo")
