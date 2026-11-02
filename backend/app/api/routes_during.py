"""场景：灾中。异常、证据、核验、影响、预报与预测。"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from sqlalchemy import func

from app.api.common import (
    ACTION_STATUSES,
    REVIEW_ACTIONS,
    REVIEW_TARGETS,
    ActionCreate,
    ActionUpdate,
    PredictBody,
    ReviewBody,
    _anomaly_row,
    _ctx,
    _err,
    _iso,
    _review_status,
    _utc_iso,
)
from app.api.deps import DbSession, WriteOperator, readable_dataset, writable_dataset
from app.config import get_settings
from app.models import (
    ActionTask,
    AnalysisRun,
    Anomaly,
    AnomalyEvidence,
    DataReadinessReport,
    EvaluationResult,
    Event,
    ForecastPoint,
    ForecastSnapshot,
    HazardObservation,
    ModelRegistry,
    PredictionResult,
    PredictionRun,
    ProvinceHourMetric,
    ReviewRecord,
    Suggestion,
    SuspensionRegionHour,
    TrainSuspension,
    WeiboClean,
    WeiboRaw,
    WeiboRegion,
)
from app.during.coupling import couple_dimensions
from app.during.multi_trend import synthesize
from app.services.metrics_registry import METRIC_META
from app.services.pipeline import NATIONAL, get_active_version, mask_text, mask_user
from app.services.prediction_service import INTERVAL_UNAVAILABLE, ML_HORIZON, build_readiness_report, run_predictions
from app.services.query_context import anomaly_query, pending_anomaly_count
from app.services.rules_loader import load_prediction_targets
from app.tasks.runner import create_task, run_task

router = APIRouter()

@router.get("/hazard")
def hazard(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode)
    q = db.query(HazardObservation).filter(
        HazardObservation.dataset_id == dataset_id, HazardObservation.event_id == event_id
    )
    if province_code:
        q = q.filter(HazardObservation.province_code == province_code)
    if ctx.strict:
        q = q.filter(HazardObservation.arrived_at.isnot(None), HazardObservation.arrived_at <= ctx.as_of)
    rows = q.order_by(HazardObservation.observed_at).limit(2000).all()
    return {
        "context": ctx.describe(),
        "items": [
            {
                "observed_at": r.observed_at.isoformat(),
                "arrived_at": _iso(r.arrived_at),
                "province_code": r.province_code,
                "metric": r.metric,
                "value": r.value,
                "unit": r.unit,
                "source": r.source,
                "original_granularity": r.original_granularity,
                "quality_flags": r.quality_flags,
            }
            for r in rows
        ],
    }
@router.get("/anomalies")
def list_anomalies(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    analysis_scope: Optional[str] = None,
    province_code: Optional[str] = None,
    dimension: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    data_version: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode, data_version, analysis_scope, dimension)
    q = anomaly_query(db, ctx)
    total = q.count()
    rows = q.order_by(Anomaly.hour_bj.desc(), Anomaly.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    scope_ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode, data_version, None, dimension)
    counts_q = anomaly_query(db, scope_ctx).with_entities(Anomaly.analysis_scope, func.count(Anomaly.id)).group_by(
        Anomaly.analysis_scope
    )
    counts = {"single": 0, "pair": 0, "joint": 0}
    counts.update({scope: n for scope, n in counts_q.all()})
    counts["unique_groups"] = (
        anomaly_query(db, scope_ctx).with_entities(func.count(func.distinct(Anomaly.group_key))).scalar() or 0
    )
    review = _review_status(db, "anomaly", [a.id for a in rows])
    return {
        "context": ctx.describe(),
        "total": total,
        "page": page,
        "page_size": page_size,
        "counts": counts,
        "pending_window": pending_anomaly_count(db, ctx),
        "items": [_anomaly_row(a, review) for a in rows],
    }


def _evidence_detail(db, e: AnomalyEvidence) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": e.id,
        "evidence_type": e.evidence_type,
        "summary": e.summary,
        "payload": e.payload,
        "ref_table": e.ref_table,
        "ref_id": e.ref_id,
        "source": None,
    }
    if e.ref_table == "weibo_raw" and e.ref_id:
        raw = db.get(WeiboRaw, int(e.ref_id))
        if raw:
            clean = db.query(WeiboClean).filter(WeiboClean.weibo_raw_id == raw.id).first()
            regions = (
                [
                    {"province_code": r.province_code, "method": r.attribution_method}
                    for r in db.query(WeiboRegion).filter(WeiboRegion.weibo_clean_id == clean.id)
                ]
                if clean
                else []
            )
            item["source"] = {
                "kind": "weibo",
                "source_id": raw.source_id,
                "user": mask_user(raw.user_id),
                "account_class": clean.account_class if clean else None,
                "content": mask_text(raw.content),
                "published_at": _iso(raw.published_at),
                "available_at": _iso(raw.available_at),
                "ingested_at": _utc_iso(raw.ingested_at),
                "url": raw.article_url,
                "publish_location": raw.publish_location,
                "region_basis": regions,
                "simulated": raw.source_id.startswith("SIM-"),
            }
    elif e.ref_table == "train_suspension" and e.ref_id:
        sus = db.get(TrainSuspension, int(e.ref_id))
        if sus:
            item["source"] = {
                "kind": "suspension",
                "record_no": sus.record_no,
                "train_code": sus.train_code,
                "scope": sus.scope,
                "segment": [sus.segment_start, sus.segment_end],
                "content": mask_text(sus.evidence_text),
                "notice_account": sus.notice_account,
                "url": sus.notice_url,
                "known_at": _iso(sus.known_at),
                "suspension_date": _iso(sus.suspension_date),
                "scope_basis": sus.scope_basis,
                "simulated": sus.record_no.startswith("SIM-"),
            }
    return item


@router.get("/anomalies/{anomaly_id}")
def anomaly_detail(
    anomaly_id: int,
    db: DbSession,
    dataset_id: str,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    a = db.get(Anomaly, anomaly_id)
    if not a or a.dataset_id != dataset_id:
        raise _err(404, "not_found", "异常不存在或不属于该数据集")
    strict = (replay_mode or ("as_known" if as_of else "retrospective")) == "as_known" and as_of is not None
    visible = not strict or (a.available_at is not None and a.available_at <= as_of)
    evidences = db.query(AnomalyEvidence).filter(AnomalyEvidence.anomaly_id == a.id).all()
    suggestions = db.query(Suggestion).filter(Suggestion.anomaly_id == a.id).all()
    reviews = (
        db.query(ReviewRecord)
        .filter(ReviewRecord.target_type == "anomaly", ReviewRecord.target_id == a.id)
        .order_by(ReviewRecord.id.desc())
        .all()
    )
    sample = None
    if a.analysis_scope == "single":
        metric = next(((e.payload or {}).get("metric_id") for e in evidences if (e.payload or {}).get("metric_id")), None)
        row = (
            db.query(ProvinceHourMetric)
            .filter(
                ProvinceHourMetric.dataset_id == dataset_id,
                ProvinceHourMetric.event_id == a.event_id,
                ProvinceHourMetric.province_code == a.province_code,
                ProvinceHourMetric.hour_bj == a.hour_bj,
                ProvinceHourMetric.metric_id == metric,
                ProvinceHourMetric.version == a.data_version,
            )
            .first()
            if metric
            else None
        )
        if row:
            sample = {"metric_id": row.metric_id, "value": row.value, "sample_size": row.sample_size, "coverage": row.coverage}
    raw_count = sum(1 for e in evidences if e.ref_table)
    return {
        "visible_at_as_of": visible,
        "anomaly": {
            **_anomaly_row(a, {a.id: reviews[0].action} if reviews else {}),
            "dataset_id": a.dataset_id,
            "event_id": a.event_id,
            "decided_at": _utc_iso(a.decided_at),
            "hazard_context": a.hazard_context,
            "sample": sample,
            "evidence_status": "sufficient" if raw_count else "insufficient",
        },
        "evidences": [_evidence_detail(db, e) for e in evidences],
        "suggestions": [
            {
                "id": s.id,
                "suggestion_code": s.suggestion_code,
                "text": s.text,
                "trigger_reason": s.trigger_reason,
                "review_status": s.review_status,
            }
            for s in suggestions
        ],
        "reviews": [
            {"id": r.id, "action": r.action, "note": r.note, "operator": r.operator, "created_at": _utc_iso(r.created_at)}
            for r in reviews
        ],
    }


@router.get("/suggestions")
def list_suggestions(
    db: DbSession, dataset_id: str, event_id: int, data_version: Optional[str] = None
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, data_version=data_version)
    rows = (
        db.query(Suggestion)
        .filter(
            Suggestion.dataset_id == dataset_id,
            Suggestion.event_id == event_id,
            Suggestion.data_version == ctx.data_version,
        )
        .order_by(Suggestion.id)
        .limit(500)
        .all()
    )
    return {
        "context": ctx.describe(),
        "items": [
            {
                "id": s.id,
                "anomaly_id": s.anomaly_id,
                "suggestion_code": s.suggestion_code,
                "text": s.text,
                "trigger_reason": s.trigger_reason,
                "review_status": s.review_status,
            }
            for s in rows
        ],
    }


@router.post("/review")
def review(body: ReviewBody, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    writable_dataset(db, body.dataset_id)
    if body.action not in REVIEW_ACTIONS:
        raise _err(400, "bad_action", f"action 仅支持 {list(REVIEW_ACTIONS)}")
    if body.target_type not in REVIEW_TARGETS:
        raise _err(400, "bad_target", f"target_type 仅支持 {REVIEW_TARGETS}")
    model = Anomaly if body.target_type == "anomaly" else Suggestion
    target = db.get(model, body.target_id)
    if target is None or target.dataset_id != body.dataset_id:
        raise _err(404, "target_not_found", "核验目标不存在或不属于该数据集")
    rec = ReviewRecord(
        dataset_id=body.dataset_id,
        target_type=body.target_type,
        target_id=body.target_id,
        action=body.action,
        note=(body.note or "")[:2000] or None,
        operator=operator,
    )
    db.add(rec)
    if body.target_type == "suggestion":
        target.review_status = body.action
    db.commit()
    return {"ok": True, "id": rec.id, "operator": operator, "created_at": _utc_iso(rec.created_at)}


@router.get("/reviews")
def list_reviews(db: DbSession, dataset_id: str, target_type: str, target_id: int) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    rows = (
        db.query(ReviewRecord)
        .filter(
            ReviewRecord.dataset_id == dataset_id,
            ReviewRecord.target_type == target_type,
            ReviewRecord.target_id == target_id,
        )
        .order_by(ReviewRecord.id.desc())
        .all()
    )
    return {
        "items": [
            {"id": r.id, "action": r.action, "note": r.note, "operator": r.operator, "created_at": _utc_iso(r.created_at)}
            for r in rows
        ]
    }


@router.get("/forecasts")
def forecasts(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, as_of=as_of, replay_mode=replay_mode)
    q = db.query(ForecastSnapshot).filter(ForecastSnapshot.dataset_id == dataset_id, ForecastSnapshot.event_id == event_id)
    if ctx.strict:
        q = q.filter(ForecastSnapshot.arrived_at <= ctx.as_of)
    rows = q.order_by(ForecastSnapshot.issued_at).all()
    latest = rows[-1] if rows else None
    points = (
        db.query(ForecastPoint).filter(ForecastPoint.snapshot_id == latest.id).order_by(ForecastPoint.lead_hours).all()
        if latest
        else []
    )
    return {
        "context": ctx.describe(),
        "items": [
            {
                "id": r.id,
                "source": r.source,
                "issued_at": r.issued_at.isoformat(),
                "arrived_at": r.arrived_at.isoformat(),
                "revision": r.revision,
            }
            for r in rows
        ],
        "latest_points": [
            {
                "valid_time": p.valid_time.isoformat(),
                "lead_hours": p.lead_hours,
                "lat": p.lat,
                "lon": p.lon,
                "metric": p.metric,
                "value": p.value,
                "unit": p.unit,
                "province_code": p.province_code,
            }
            for p in points
        ],
    }


@router.post("/predictions/run")
def predictions_run(body: PredictBody, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    ds = writable_dataset(db, body.dataset_id)
    ev = db.get(Event, body.event_id)
    if not ev or ev.dataset_id != body.dataset_id:
        raise _err(404, "not_found", "事件不存在或不属于该数据集")
    origin = body.origin_time.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    task = create_task(db, "prediction", dataset_id=body.dataset_id, event_id=body.event_id)
    try:
        task = run_task(db, task.id, lambda: run_predictions(db, body.dataset_id, body.event_id, origin, data_mode=ds.data_mode))
    except Exception as exc:  # noqa: BLE001
        raise _err(500, "prediction_failed", str(exc), task_id=task.id) from exc
    return {"task_id": task.id, "status": task.status, "result": task.result, "operator": operator}


@router.get("/predictions")
def list_predictions(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    origin_time: Optional[datetime] = None,
    target_id: Optional[str] = None,
    province_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode)
    runs = db.query(PredictionRun).filter(PredictionRun.dataset_id == dataset_id, PredictionRun.event_id == event_id)
    if origin_time:
        runs = runs.filter(PredictionRun.origin_time == origin_time)
    if ctx.strict:
        runs = runs.filter(PredictionRun.origin_time <= ctx.as_of)
    run = runs.order_by(PredictionRun.id.desc()).first()
    available_origins = [
        r.origin_time.isoformat()
        for r in db.query(PredictionRun.origin_time)
        .filter(PredictionRun.dataset_id == dataset_id, PredictionRun.event_id == event_id)
        .distinct()
        .order_by(PredictionRun.origin_time)
    ]
    cfg = load_prediction_targets()
    targets = {t["id"]: t for t in cfg.get("targets", [])}
    meta = {
        "targets": [
            {"id": t["id"], "name": METRIC_META.get(t["id"], {}).get("name", t["id"]), "unit": t.get("unit")}
            for t in targets.values()
        ],
        "horizons": cfg.get("horizons_hours", [1, 3, 6, 12, 24]),
        "ml_horizon": ML_HORIZON,
        "cross_event_validated": False,
        "interval_reason": INTERVAL_UNAVAILABLE,
    }
    if run is None:
        return {"context": ctx.describe(), "run": None, "items": [], "multi": [], "available_origins": available_origins, **meta}
    q = db.query(PredictionResult).filter(PredictionResult.run_id == run.id)
    if target_id:
        q = q.filter(PredictionResult.target_id == target_id)
    if province_code:
        q = q.filter(PredictionResult.province_code == province_code)
    rows = q.order_by(PredictionResult.province_code, PredictionResult.lead_hours).limit(5000).all()
    items = [
        {
            "target_id": r.target_id,
            "unit": targets.get(r.target_id, {}).get("unit"),
            "province_code": r.province_code,
            "origin_time": r.origin_time.isoformat(),
            "valid_time": r.valid_time.isoformat(),
            "lead_hours": r.lead_hours,
            "point_pred": r.point_pred,
            "interval_low": r.interval_low,
            "interval_high": r.interval_high,
            "interval_reason": None if r.interval_low is not None else INTERVAL_UNAVAILABLE,
            "status": r.status,
            "reason": r.reason,
            "model_version": r.model_version,
            "train_cutoff": _iso(r.train_cutoff),
            "data_version": r.data_version,
            "quality_status": r.quality_status,
        }
        for r in rows
    ]
    return {
        "context": ctx.describe(),
        "run": {
            "id": run.id,
            "origin_time": run.origin_time.isoformat(),
            "model_version": run.model_version,
            "status": run.status,
            "created_at": _utc_iso(run.created_at),
        },
        "available_origins": available_origins,
        **meta,
        "items": items,
        "multi": synthesize(items),
    }


@router.get("/models")
def list_models(db: DbSession) -> dict[str, Any]:
    mode = get_settings().data_mode
    rows = db.query(ModelRegistry).filter(ModelRegistry.data_mode == mode).all()
    return {
        "items": [
            {
                "model_key": m.model_key,
                "target_id": m.target_id,
                "horizon_hours": m.horizon_hours,
                "model_kind": m.model_kind,
                "data_mode": m.data_mode,
                "metrics": m.metrics,
                "feature_contract": m.feature_contract,
                "train_window": m.train_window,
                "version": m.version,
            }
            for m in rows
        ]
    }


@router.get("/evaluations")
def list_evaluations(db: DbSession, dataset_id: str) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    rows = db.query(EvaluationResult).filter(EvaluationResult.dataset_id == dataset_id).order_by(EvaluationResult.id.desc()).all()
    return {
        "items": [
            {
                "target_id": r.target_id,
                "horizon_hours": r.horizon_hours,
                "split_info": r.split_info,
                "metrics": r.metrics,
                "notes": r.notes,
            }
            for r in rows
        ]
    }


@router.get("/readiness")
def readiness(db: DbSession, dataset_id: str) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    row = (
        db.query(DataReadinessReport)
        .filter(DataReadinessReport.dataset_id == dataset_id)
        .order_by(DataReadinessReport.created_at.desc(), DataReadinessReport.id.desc())
        .first()
    )
    if not row:
        return {"report": build_readiness_report(db, dataset_id)}
    return {"report": row.report, "created_at": _utc_iso(row.created_at)}
TOPIC_KEYWORDS = ["求助", "停运", "交通", "出行", "预报", "路径", "通知", "停电", "积水"]


@router.get("/analysis/topics")
def analysis_topics(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode)
    q = (
        db.query(WeiboRaw.content)
        .join(WeiboClean, WeiboClean.weibo_raw_id == WeiboRaw.id)
        .filter(WeiboClean.dataset_id == dataset_id, WeiboClean.event_id == event_id, WeiboClean.account_class == "personal")
    )
    if province_code:
        q = q.join(WeiboRegion, WeiboRegion.weibo_clean_id == WeiboClean.id).filter(WeiboRegion.province_code == province_code)
    if start:
        q = q.filter(WeiboClean.hour_bj >= start)
    if end:
        q = q.filter(WeiboClean.hour_bj <= end)
    if ctx.strict:
        q = q.filter(WeiboClean.available_at.isnot(None), WeiboClean.available_at <= ctx.as_of)
    counter: Counter[str] = Counter()
    total = 0
    for (content,) in q.limit(20000):
        total += 1
        for kw in TOPIC_KEYWORDS:
            if kw in (content or ""):
                counter[kw] += 1
    return {
        "context": ctx.describe(),
        "method": "关键词规则计数（个人微博），非主题模型",
        "sample_size": total,
        "items": [{"keyword": k, "count": counter.get(k, 0)} for k in TOPIC_KEYWORDS if counter.get(k)],
    }
@router.get("/impact")
def impact(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode)
    sq = db.query(TrainSuspension).filter(TrainSuspension.dataset_id == dataset_id, TrainSuspension.event_id == event_id)
    if ctx.strict:
        sq = sq.filter(TrainSuspension.known_at.isnot(None), TrainSuspension.known_at <= ctx.as_of)
    suspensions = sq.order_by(TrainSuspension.suspension_date).all()
    mapping: dict[int, list[SuspensionRegionHour]] = {}
    for r in db.query(SuspensionRegionHour).filter(
        SuspensionRegionHour.dataset_id == dataset_id, SuspensionRegionHour.event_id == event_id
    ):
        mapping.setdefault(r.suspension_id, []).append(r)
    run = (
        db.query(AnalysisRun)
        .filter(AnalysisRun.dataset_id == dataset_id, AnalysisRun.data_version == ctx.data_version)
        .first()
    )
    pending_ids = {p["suspension_id"]: p["reason"] for p in ((run.report or {}).get("suspensions", {}).get("pending_review", []) if run else [])}
    runs: dict[str, dict[str, Any]] = {}
    rows = []
    for s in suspensions:
        hits = mapping.get(s.id, [])
        if province_code and not any(h.province_code == province_code for h in hits):
            continue
        stations = sorted({st for h in hits for st in (h.stations or [])})
        status = "pending_review" if s.id in pending_ids else ("mapped" if hits else "unmapped")
        rows.append(
            {
                "id": s.id,
                "record_no": s.record_no,
                "train_code": s.train_code,
                "suspension_date": _iso(s.suspension_date),
                "known_at": _iso(s.known_at),
                "scope": s.scope,
                "segment": [s.segment_start, s.segment_end],
                "provinces": sorted({h.province_code for h in hits}),
                "stations": stations,
                "mapping_status": status,
                "pending_reason": pending_ids.get(s.id),
                "basis": sorted({h.estimate_basis for h in hits}),
                "notice_account": s.notice_account,
            }
        )
        for h in hits:
            key = h.run_key or s.train_code
            r = runs.setdefault(key, {"run_key": key, "train_code": s.train_code, "provinces": set(), "first_hour": h.hour_bj, "last_hour": h.hour_bj})
            r["provinces"].add(h.province_code)
            r["first_hour"] = min(r["first_hour"], h.hour_bj)
            r["last_hour"] = max(r["last_hour"], h.hour_bj)
    return {
        "context": ctx.describe(),
        "suspensions": rows[:500],
        "run_instances": [
            {**r, "provinces": sorted(r["provinces"]), "first_hour": r["first_hour"].isoformat(), "last_hour": r["last_hour"].isoformat()}
            for r in runs.values()
        ],
        "recovery": {"status": "not_connected", "message": "恢复/复运数据源未接入，不推断恢复时间"},
    }


# ---------------------------------------------------------------- business actions


def _action_row(t: ActionTask) -> dict[str, Any]:
    return {
        "id": t.id,
        "suggestion_id": t.suggestion_id,
        "title": t.title,
        "owner": t.owner,
        "due_at": _iso(t.due_at),
        "status": t.status,
        "receipt": t.receipt,
        "review_note": t.review_note,
        "created_by": t.created_by,
        "created_at": _utc_iso(t.created_at),
        "updated_at": _utc_iso(t.updated_at),
    }


@router.get("/actions")
def list_actions(db: DbSession, dataset_id: str, event_id: int) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    rows = (
        db.query(ActionTask)
        .filter(ActionTask.dataset_id == dataset_id, ActionTask.event_id == event_id)
        .order_by(ActionTask.id.desc())
        .all()
    )
    return {"items": [_action_row(t) for t in rows]}


@router.post("/actions")
def create_action(body: ActionCreate, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    writable_dataset(db, body.dataset_id)
    s = db.get(Suggestion, body.suggestion_id)
    if s is None or s.dataset_id != body.dataset_id:
        raise _err(404, "not_found", "建议不存在或不属于该数据集")
    if s.review_status != "approve":
        raise _err(409, "not_approved", "候选建议需先经人工核验通过，才能形成行动任务")
    t = ActionTask(
        dataset_id=body.dataset_id,
        event_id=s.event_id,
        suggestion_id=s.id,
        title=(body.title or s.text)[:2000],
        owner=body.owner,
        due_at=body.due_at,
        status="open",
        created_by=operator,
    )
    db.add(t)
    db.commit()
    db.refresh(t)
    return _action_row(t)


@router.patch("/actions/{action_id}")
def update_action(action_id: int, body: ActionUpdate, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    writable_dataset(db, body.dataset_id)
    t = db.get(ActionTask, action_id)
    if t is None or t.dataset_id != body.dataset_id:
        raise _err(404, "not_found", "行动任务不存在或不属于该数据集")
    if body.status is not None:
        if body.status not in ACTION_STATUSES:
            raise _err(400, "bad_status", f"status 仅支持 {ACTION_STATUSES}")
        if body.status == "closed" and not (body.receipt or t.receipt):
            raise _err(409, "receipt_required", "销项前需要填写回执")
        t.status = body.status
    for field in ("owner", "due_at", "receipt", "review_note"):
        value = getattr(body, field)
        if value is not None:
            setattr(t, field, value)
    db.commit()
    db.refresh(t)
    return _action_row(t)


COUPLING_METRICS = {
    "personal_weibo_count": "social",
    "official_weibo_count": "organizational",
    "affected_trains": "physical",
}


@router.get("/coupling")
def coupling(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    max_lag_hours: int = Query(6, ge=0, le=24),
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    data_version: Optional[str] = None,
) -> dict[str, Any]:
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode, data_version=data_version)
    version = ctx.data_version or get_active_version(db, dataset_id, event_id)
    query = db.query(ProvinceHourMetric).filter(
        ProvinceHourMetric.dataset_id == dataset_id,
        ProvinceHourMetric.event_id == event_id,
        ProvinceHourMetric.version == version,
        ProvinceHourMetric.metric_id.in_(list(COUPLING_METRICS)),
        ProvinceHourMetric.province_code != NATIONAL,
    )
    if province_code:
        query = query.filter(ProvinceHourMetric.province_code == province_code)
    if ctx.strict:
        query = query.filter(ProvinceHourMetric.available_at.isnot(None), ProvinceHourMetric.available_at <= ctx.as_of)
    by_province: dict[str, dict[str, dict]] = {}
    for row in query:
        if row.value is None:
            continue
        dim = COUPLING_METRICS[row.metric_id]
        by_province.setdefault(row.province_code, {}).setdefault(dim, {})[row.hour_bj] = row.value
    pairs = []
    for prov, series in sorted(by_province.items()):
        for item in couple_dimensions(series, max_lag_hours):
            pairs.append({"province_code": prov, **item})
    return {"context": ctx.describe(), "max_lag_hours": max_lag_hours, "pairs": pairs}
