"""场景：复用。健康检查、指标、总览、覆盖、重跑与运行记录。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.common import _anomaly_row, _ctx, _err, _iso, _utc_iso
from app.api.deps import DbSession, WriteOperator, readable_dataset, writable_dataset
from app.config import get_settings
from app.models import (
    AnalysisRun,
    Anomaly,
    ForecastSnapshot,
    HazardObservation,
    ProvinceHourMetric,
    ReviewRecord,
    TaskRun,
    TrainSuspension,
    WeiboRaw,
    Dataset,
    MetricRegistry,
)
from app.services.bootstrap import ensure_metrics
from app.services.metrics_registry import METRIC_META
from app.services.pipeline import NATIONAL, get_active_version, run_full_pipeline
from app.services.query_context import (
    QueryContext,
    anomaly_query,
    card_hour,
    metric_query,
    pending_anomaly_count,
    visible_metrics,
)
from app.services.rules_loader import load_rules
from app.tasks.runner import create_task, run_task

router = APIRouter()

@router.get("/health")
def health(db: DbSession) -> dict[str, Any]:
    from sqlalchemy import text

    try:
        db.execute(text("SELECT 1"))
        db_ok, err = True, None
    except Exception as e:  # noqa: BLE001
        db_ok, err = False, str(e)
    settings = get_settings()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": db_ok,
        "error": err,
        "data_mode": settings.data_mode,
        "write_requires_key": bool(settings.api_key) or settings.data_mode == "real",
        "seed_allowed": settings.data_mode == "demo",
        "time": datetime.utcnow().isoformat() + "Z",
    }


@router.get("/datasets")
def list_datasets(db: DbSession) -> dict[str, Any]:
    mode = get_settings().data_mode
    rows = db.query(Dataset).filter(Dataset.data_mode == mode).all()
    return {
        "data_mode": mode,
        "items": [
            {"id": d.id, "name": d.name, "data_mode": d.data_mode, "description": d.description} for d in rows
        ],
    }
@router.get("/metrics/registry")
def metric_registry(db: DbSession) -> dict[str, Any]:
    ensure_metrics(db)
    rows = db.query(MetricRegistry).filter(MetricRegistry.active.is_(True)).all()
    rules = load_rules()
    return {
        "rule_version": rules.get("version"),
        "rules": {k: rules.get(k) for k in ("single", "pair", "joint", "accounts", "replay")},
        "items": [
            {
                "id": m.id,
                "name": m.name,
                "dimension": m.dimension,
                "unit": METRIC_META.get(m.id, {}).get("unit", m.unit),
                "description": METRIC_META.get(m.id, {}).get("description", m.description),
                "aggregation": m.aggregation,
                "numerator": METRIC_META.get(m.id, {}).get("numerator"),
                "denominator": METRIC_META.get(m.id, {}).get("denominator"),
                "dedup_key": METRIC_META.get(m.id, {}).get("dedup_key"),
                "national_rule": METRIC_META.get(m.id, {}).get("national_rule"),
                "version": m.version,
            }
            for m in rows
        ],
    }


@router.get("/metrics/series")
def metric_series(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    metric_id: Optional[str] = None,
    province_code: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    data_version: Optional[str] = None,
    include_national: bool = False,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode, data_version)
    q = metric_query(db, ctx, include_national=include_national)
    if metric_id:
        q = q.filter(ProvinceHourMetric.metric_id.in_(metric_id.split(",")))
    rows, unknown = visible_metrics(db, ctx, q)
    return {
        "context": ctx.describe(),
        "granularity": "hour",
        "strict_unavailable": unknown,
        "items": [
            {
                "province_code": r.province_code,
                "hour_bj": r.hour_bj.isoformat(),
                "metric_id": r.metric_id,
                "value": r.value,
                "sample_size": r.sample_size,
                "coverage": r.coverage,
                "quality_status": r.quality_status,
                "unit": METRIC_META.get(r.metric_id, {}).get("unit"),
                "version": r.version,
                "available_at": _iso(r.available_at),
            }
            for r in rows
        ],
    }
@router.get("/tasks/{task_id}")
def get_task(task_id: int, db: DbSession) -> dict[str, Any]:
    t = db.get(TaskRun, task_id)
    if not t:
        raise _err(404, "not_found", "任务不存在")
    return {
        "id": t.id,
        "task_type": t.task_type,
        "status": t.status,
        "progress": t.progress,
        "message": t.message,
        "result": t.result,
    }
@router.post("/pipeline/rerun")
def pipeline_rerun(
    db: DbSession,
    operator: WriteOperator,
    dataset_id: str = Query(...),
    event_id: Optional[int] = Query(None),
) -> dict[str, Any]:
    writable_dataset(db, dataset_id)
    task = create_task(db, "pipeline_rerun", dataset_id=dataset_id, event_id=event_id)
    task = run_task(db, task.id, lambda: run_full_pipeline(db, dataset_id, event_id=event_id, trigger=f"rerun:{operator}"))
    return {"task_id": task.id, "status": task.status, **(task.result or {})}


@router.get("/analysis/runs")
def analysis_runs(db: DbSession, dataset_id: str, event_id: Optional[int] = None) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    q = db.query(AnalysisRun).filter(AnalysisRun.dataset_id == dataset_id)
    if event_id is not None:
        q = q.filter(AnalysisRun.event_id == event_id)
    rows = q.order_by(AnalysisRun.id.desc()).limit(50).all()
    return {
        "items": [
            {
                "id": r.id,
                "event_id": r.event_id,
                "data_version": r.data_version,
                "status": r.status,
                "rule_version": r.rule_version,
                "trigger": r.trigger,
                "message": r.message,
                "started_at": _utc_iso(r.started_at),
                "finished_at": _utc_iso(r.finished_at),
                "active": r.data_version is not None and r.data_version == get_active_version(db, dataset_id, r.event_id),
            }
            for r in rows
        ]
    }


@router.get("/coverage")
def coverage(db: DbSession, dataset_id: str, event_id: int, data_version: Optional[str] = None) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, data_version=data_version)
    run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.dataset_id == dataset_id, AnalysisRun.data_version == ctx.data_version)
        .first()
    )
    report = (run.report or {}) if run else {}
    metric_rows = (
        metric_query(db, ctx)
        .with_entities(
            ProvinceHourMetric.province_code,
            ProvinceHourMetric.metric_id,
            func.count(ProvinceHourMetric.id),
            func.sum(func.coalesce(ProvinceHourMetric.sample_size, 0)),
        )
        .group_by(ProvinceHourMetric.province_code, ProvinceHourMetric.metric_id)
        .all()
    )
    matrix: dict[str, dict[str, Any]] = {}
    low_sample: dict[str, int] = {}
    min_samples = int(load_rules().get("single", {}).get("min_samples", 6))
    for prov, metric, hours, samples in metric_rows:
        matrix.setdefault(prov, {})[metric] = {"hours": hours, "samples": int(samples or 0)}
    for prov, n in (
        metric_query(db, ctx)
        .filter(ProvinceHourMetric.metric_id == "negative_ratio", ProvinceHourMetric.sample_size < min_samples)
        .with_entities(ProvinceHourMetric.province_code, func.count(ProvinceHourMetric.id))
        .group_by(ProvinceHourMetric.province_code)
    ):
        low_sample[prov] = n
    unknown_arrival = (
        metric_query(db, ctx).filter(ProvinceHourMetric.available_at.is_(None)).count()
    )
    end_time = ctx.event.end_time or ctx.as_of or ctx.event.start_time
    event_hours = int((end_time - ctx.event.start_time).total_seconds() // 3600) + 1
    return {
        "context": ctx.describe(),
        "event_hours": event_hours,
        "run": {"id": run.id, "status": run.status, "finished_at": _utc_iso(run.finished_at)} if run else None,
        "tasks": report.get("anomalies", {}).get("tasks", {}),
        "pending_mapping": report.get("suspensions", {}).get("pending_review", []),
        "account_classes": report.get("clean", {}).get("account_classes", {}),
        "untrusted_arrival": report.get("clean", {}).get("untrusted_arrival"),
        "org_covered_provinces": report.get("metrics", {}).get("org_covered_provinces", []),
        "metric_matrix": matrix,
        "low_sample_hours": low_sample,
        "unknown_arrival_metric_rows": unknown_arrival,
        "proxy_sources": [
            {"metric": "rainfall_hourly_proxy", "note": "日雨量平均拆分到小时的代理值"},
            {"metric": "affected_trains(seed_force_province)", "note": "演示数据强制归省，仅 demo 模式生效"},
        ],
    }
def _freshness(db, ctx: QueryContext) -> list[dict[str, Any]]:
    def latest(model, col, *filters):
        q = db.query(func.max(col)).filter(model.dataset_id == ctx.dataset_id, model.event_id == ctx.event_id, *filters)
        if ctx.strict:
            q = q.filter(col <= ctx.as_of)
        return q.scalar()

    return [
        {"source": "微博", "latest": _iso(latest(WeiboRaw, WeiboRaw.available_at))},
        {"source": "停运公告", "latest": _iso(latest(TrainSuspension, TrainSuspension.known_at))},
        {"source": "台风实况", "latest": _iso(latest(HazardObservation, HazardObservation.arrived_at))},
        {"source": "预报快照", "latest": _iso(latest(ForecastSnapshot, ForecastSnapshot.arrived_at))},
    ]


@router.get("/dashboard/summary")
def dashboard_summary(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    hour_bj: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    province_code: Optional[str] = None,
    data_version: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode, data_version=data_version)
    hour = card_hour(ctx, hour_bj)
    has_data = metric_query(db, ctx, include_national=True).first() is not None
    if not has_data:
        return {
            "context": ctx.describe(),
            "data_mode": ctx.dataset.data_mode,
            "empty": True,
            "message": "当前数据集没有分析结果（真实数据未导入或尚未运行分析）",
            "cards": {},
        }

    def card(metric_id: str) -> dict[str, Any]:
        base = db.query(ProvinceHourMetric).filter(
            ProvinceHourMetric.dataset_id == dataset_id,
            ProvinceHourMetric.event_id == event_id,
            ProvinceHourMetric.metric_id == metric_id,
            ProvinceHourMetric.version == ctx.data_version,
            ProvinceHourMetric.hour_bj == hour,
        )
        rows = base.all()
        unknown = 0
        if ctx.strict:
            unknown = sum(1 for r in rows if r.available_at is None)
            rows = [r for r in rows if r.available_at is not None and r.available_at <= ctx.as_of]
        provinces = {r.province_code: r.value for r in rows if r.province_code != NATIONAL}
        national = next((r for r in rows if r.province_code == NATIONAL), None)
        focus = provinces.get(province_code) if province_code else (national.value if national else None)
        focus_row = next((r for r in rows if r.province_code == (province_code or NATIONAL)), None)
        meta = METRIC_META.get(metric_id, {})
        return {
            "metric_id": metric_id,
            "name": meta.get("name", metric_id),
            "unit": meta.get("unit"),
            "hour_bj": hour.isoformat(),
            "provinces": provinces,
            "value": focus,
            "sample_size": focus_row.sample_size if focus_row else None,
            "aggregation": meta.get("national_rule") if not province_code else "省级值",
            "quality": "ok" if focus is not None else ("strict_unavailable" if unknown else "insufficient"),
        }

    anomalies = anomaly_query(db, ctx)
    counts = dict(anomalies.with_entities(Anomaly.analysis_scope, func.count(Anomaly.id)).group_by(Anomaly.analysis_scope).all())
    reviewed_ids = {
        r.target_id for r in db.query(ReviewRecord.target_id).filter(ReviewRecord.dataset_id == dataset_id, ReviewRecord.target_type == "anomaly")
    }
    to_review = [
        _anomaly_row(a, {})
        for a in anomalies.order_by(Anomaly.hour_bj.desc(), Anomaly.score.desc()).limit(60).all()
        if a.id not in reviewed_ids
    ][:8]
    ev = ctx.event
    reference = ctx.as_of or hour
    if reference < ev.start_time:
        phase = "pre"
    elif ev.end_time is None or reference <= ev.end_time:
        phase = "during"
    else:
        phase = "post"
    return {
        "context": ctx.describe(),
        "data_mode": ctx.dataset.data_mode,
        "empty": False,
        "phase": phase,
        "card_hour": hour.isoformat(),
        "event": {
            "id": ev.id,
            "name": ev.name,
            "event_code": ev.event_code,
            "start_time": ev.start_time.isoformat(),
            "end_time": ev.end_time.isoformat() if ev.end_time else None,
            "status": ev.status,
        },
        "banner": "模拟数据" if ctx.dataset.data_mode == "demo" else "真实数据",
        "cards": {
            "social_discussion": card("personal_weibo_count"),
            "social_negative_ratio": card("negative_ratio"),
            "org_official": card("official_weibo_count"),
            "physical_trains": card("affected_trains"),
            "help_requests": card("help_request_count"),
        },
        "anomaly_counts": {"single": counts.get("single", 0), "pair": counts.get("pair", 0), "joint": counts.get("joint", 0)},
        "pending_window": pending_anomaly_count(db, ctx),
        "to_review": to_review,
        "freshness": _freshness(db, ctx),
    }
