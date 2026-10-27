from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import func

from app.api.deps import DbSession, WriteOperator, readable_dataset, writable_dataset
from app.config import get_settings
from app.models import (
    ActionTask,
    AnalysisRun,
    Anomaly,
    AnomalyEvidence,
    DataBatch,
    DataReadinessReport,
    Dataset,
    EvaluationResult,
    Event,
    ForecastPoint,
    ForecastSnapshot,
    HazardObservation,
    ImportErrorRow,
    MetricRegistry,
    ModelRegistry,
    PredictionResult,
    PredictionRun,
    ProvinceHourMetric,
    ReviewRecord,
    Suggestion,
    SuspensionRegionHour,
    TaskRun,
    TrainSuspension,
    WeiboClean,
    WeiboRaw,
    WeiboRegion,
)
from app.services.bootstrap import ensure_dataset, ensure_metrics
from app.services.export_service import export_anomalies_csv, export_metrics_csv
from app.services.import_service import (
    ALLOWED_SUFFIXES,
    IMPORT_SOURCES,
    ImportRejected,
    commit_weibo_import,
    precheck,
)
from app.services.metrics_registry import METRIC_META
from app.services.pipeline import NATIONAL, get_active_version, mask_text, mask_user, run_full_pipeline
from app.services.demo_setup import seed_and_prepare_demo
from app.services.prediction_service import (
    INTERVAL_UNAVAILABLE,
    ML_HORIZON,
    build_readiness_report,
    run_predictions,
)
from app.services.query_context import (
    QueryContext,
    anomaly_query,
    card_hour,
    metric_query,
    pending_anomaly_count,
    resolve_context,
    visible_metrics,
)
from app.services.rules_loader import load_prediction_targets, load_rules
from app.tasks.runner import create_task, run_task

router = APIRouter(prefix="/api/v1")

REVIEW_ACTIONS = {"approve": "核验通过", "reject": "驳回", "need_evidence": "待补证据"}
REVIEW_TARGETS = ("anomaly", "suggestion")
ACTION_STATUSES = ("open", "in_progress", "done", "closed", "cancelled")


def _err(status: int, code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"error_code": code, "message": message, **extra})


def _iso(dt: datetime | None) -> str | None:
    """Event and observation times: naive Beijing wall time."""
    return dt.isoformat() if dt else None


def _utc_iso(dt: datetime | None) -> str | None:
    """System timestamps (created/finished/decided/ingested) are stored as naive UTC; mark them explicitly."""
    return dt.isoformat() + "Z" if dt else None


def _ctx(
    db,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    data_version: Optional[str] = None,
    analysis_scope: Optional[str] = None,
    dimension: Optional[str] = None,
) -> QueryContext:
    return resolve_context(
        db,
        dataset_id,
        event_id,
        province_code=province_code,
        start=start,
        end=end,
        as_of=as_of,
        replay_mode=replay_mode,
        data_version=data_version,
        analysis_scope=analysis_scope,
        dimension=dimension,
    )


class EventCreate(BaseModel):
    dataset_id: str
    event_code: str
    name: str
    external_typhoon_id: Optional[str] = None
    start_time: datetime
    end_time: datetime
    status: str = "tracking"
    config_version: str = "v1"


class ReviewBody(BaseModel):
    target_type: str
    target_id: int
    action: str
    note: Optional[str] = None
    dataset_id: str


class PredictBody(BaseModel):
    dataset_id: str
    event_id: int
    origin_time: datetime


class ActionCreate(BaseModel):
    dataset_id: str
    suggestion_id: int
    title: Optional[str] = None
    owner: Optional[str] = None
    due_at: Optional[datetime] = None


class ActionUpdate(BaseModel):
    dataset_id: str
    status: Optional[str] = None
    owner: Optional[str] = None
    due_at: Optional[datetime] = None
    receipt: Optional[str] = None
    review_note: Optional[str] = None


# ---------------------------------------------------------------- system


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


@router.post("/admin/seed")
def admin_seed(db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    if get_settings().data_mode != "demo":
        raise _err(403, "seed_forbidden", "真实模式不允许生成演示数据")
    return {**seed_and_prepare_demo(db), "operator": operator}


# ---------------------------------------------------------------- events


@router.get("/events")
def list_events(db: DbSession, dataset_id: str = Query(...)) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    rows = db.query(Event).filter(Event.dataset_id == dataset_id).order_by(Event.start_time).all()
    return {
        "items": [
            {
                "id": e.id,
                "dataset_id": e.dataset_id,
                "event_code": e.event_code,
                "name": e.name,
                "external_typhoon_id": e.external_typhoon_id,
                "start_time": e.start_time.isoformat(),
                "end_time": e.end_time.isoformat(),
                "status": e.status,
                "config_version": e.config_version,
                "active_version": get_active_version(db, dataset_id, e.id),
            }
            for e in rows
        ]
    }


@router.post("/events")
def create_event(body: EventCreate, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    settings = get_settings()
    if body.end_time <= body.start_time:
        raise _err(400, "bad_time_range", "结束时间必须晚于开始时间")
    if writable_dataset(db, body.dataset_id, allow_create=True) is None:
        ensure_dataset(db, body.dataset_id, settings.data_mode)
    exists = (
        db.query(Event).filter(Event.dataset_id == body.dataset_id, Event.event_code == body.event_code).first()
    )
    if exists:
        raise _err(409, "event_exists", "事件已存在")
    e = Event(**body.model_dump())
    db.add(e)
    db.commit()
    db.refresh(e)
    return {"id": e.id, "operator": operator}


# ---------------------------------------------------------------- metrics


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


# ---------------------------------------------------------------- anomalies


def _review_status(db, target_type: str, target_ids: list[int]) -> dict[int, str]:
    if not target_ids:
        return {}
    out: dict[int, str] = {}
    rows = (
        db.query(ReviewRecord)
        .filter(ReviewRecord.target_type == target_type, ReviewRecord.target_id.in_(target_ids))
        .order_by(ReviewRecord.id)
        .all()
    )
    for r in rows:
        out[r.target_id] = r.action
    return out


def _anomaly_row(a: Anomaly, review: dict[int, str]) -> dict[str, Any]:
    return {
        "id": a.id,
        "analysis_scope": a.analysis_scope,
        "dimensions": a.dimensions,
        "anomaly_type": a.anomaly_type,
        "province_code": a.province_code,
        "hour_bj": a.hour_bj.isoformat(),
        "available_at": _iso(a.available_at),
        "requires_future_window": a.requires_future_window,
        "nature": a.nature,
        "score": a.score,
        "baseline": a.baseline,
        "threshold": a.threshold,
        "quality_status": a.quality_status,
        "rule_version": a.rule_version,
        "data_version": a.data_version,
        "group_key": a.group_key,
        "explanation": a.explanation,
        "review_status": review.get(a.id, "pending"),
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


# ---------------------------------------------------------------- import


@router.get("/import/sources")
def import_sources() -> dict[str, Any]:
    return {"items": IMPORT_SOURCES, "max_upload_mb": get_settings().max_upload_mb}


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    settings = get_settings()
    suffix = Path(file.filename or "upload.csv").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise _err(400, "bad_format", "仅支持 CSV/XLSX")
    data = await file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise _err(400, "file_too_large", f"文件超过 {settings.max_upload_mb} MB")
    if not data:
        raise _err(400, "empty_file", "文件为空")
    return data, suffix


def _mapping(raw: Optional[str]) -> dict[str, str] | None:
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _err(400, "bad_mapping", "字段映射必须是 JSON 对象") from exc
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        raise _err(400, "bad_mapping", "字段映射必须是 {源列: 目标列}")
    return value


@router.post("/import/precheck")
async def import_precheck(
    db: DbSession,
    operator: WriteOperator,
    file: UploadFile = File(...),
    entity: str = Form("weibo"),
    dataset_id: str = Form(...),
    event_id: int = Form(...),
    column_mapping: Optional[str] = Form(None),
):
    writable_dataset(db, dataset_id, allow_create=True)
    data, suffix = await _read_upload(file)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        report = precheck(tmp_path, data, entity, dataset_id, event_id, _mapping(column_mapping))
    except ImportRejected as exc:
        raise _err(400, exc.code, exc.message, **exc.extra) from exc
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)
    report["file_name"] = file.filename
    return report


@router.post("/import/commit")
async def import_commit(
    db: DbSession,
    operator: WriteOperator,
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    event_id: int = Form(...),
    precheck_token: str = Form(...),
    column_mapping: Optional[str] = Form(None),
    error_policy: str = Form("strict"),
    confirm_skip: bool = Form(False),
):
    settings = get_settings()
    writable_dataset(db, dataset_id, allow_create=True)
    data, suffix = await _read_upload(file)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        return commit_weibo_import(
            db,
            dataset_id,
            event_id,
            tmp_path,
            data,
            precheck_token,
            data_mode=settings.data_mode,
            column_mapping=_mapping(column_mapping),
            error_policy=error_policy,
            confirm_skip=confirm_skip,
            file_name=Path(file.filename).name if file.filename else None,
        )
    except ImportRejected as exc:
        raise _err(400, exc.code, exc.message, **exc.extra) from exc
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)


@router.get("/import/batches")
def import_batches(db: DbSession, dataset_id: str) -> dict[str, Any]:
    readable_dataset(db, dataset_id)
    rows = db.query(DataBatch).filter(DataBatch.dataset_id == dataset_id).order_by(DataBatch.id.desc()).limit(50).all()
    return {
        "items": [
            {
                "id": b.id,
                "event_id": b.event_id,
                "source_type": b.source_type,
                "status": b.status,
                "file_name": b.file_name,
                "created_at": _utc_iso(b.created_at),
                "completed_at": _utc_iso(b.completed_at),
                "inserted": (b.report or {}).get("inserted") if b.source_type != "seed" else (b.report or {}).get("weibo"),
                "excluded_rows": len((b.report or {}).get("excluded_rows") or []),
                "analysis_status": (b.report or {}).get("analysis_status"),
            }
            for b in rows
        ]
    }


@router.get("/import/errors/{batch_id}")
def import_errors(batch_id: int, db: DbSession, dataset_id: str) -> dict[str, Any]:
    batch = db.get(DataBatch, batch_id)
    if not batch or batch.dataset_id != dataset_id:
        raise _err(404, "not_found", "批次不存在或不属于该数据集")
    readable_dataset(db, dataset_id)
    rows = db.query(ImportErrorRow).filter(ImportErrorRow.batch_id == batch_id).order_by(ImportErrorRow.row_number).all()
    return {
        "batch_id": batch_id,
        "status": batch.status,
        "items": [{"row_number": r.row_number, "reason": r.reason, "raw_payload": r.raw_payload} for r in rows],
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


# ---------------------------------------------------------------- export


@router.get("/export/anomalies")
def export_anomalies(
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
):
    ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode, data_version, analysis_scope, dimension)
    content = export_anomalies_csv(db, ctx)
    name = f"anomalies_{dataset_id}_{event_id}_{ctx.data_version}.csv"
    return PlainTextResponse(
        "\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/export/metrics")
def export_metrics(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    data_version: Optional[str] = None,
):
    ctx = _ctx(db, dataset_id, event_id, province_code, start, end, as_of, replay_mode, data_version)
    content = export_metrics_csv(db, ctx)
    name = f"metrics_{dataset_id}_{event_id}_{ctx.data_version}.csv"
    return PlainTextResponse(
        "\ufeff" + content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# ---------------------------------------------------------------- forecasts & predictions


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
        return {"context": ctx.describe(), "run": None, "items": [], "available_origins": available_origins, **meta}
    q = db.query(PredictionResult).filter(PredictionResult.run_id == run.id)
    if target_id:
        q = q.filter(PredictionResult.target_id == target_id)
    if province_code:
        q = q.filter(PredictionResult.province_code == province_code)
    rows = q.order_by(PredictionResult.province_code, PredictionResult.lead_hours).limit(5000).all()
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
        "items": [
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
        ],
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


# ---------------------------------------------------------------- pipeline & versions


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
    event_hours = int((ctx.event.end_time - ctx.event.start_time).total_seconds() // 3600) + 1
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


# ---------------------------------------------------------------- dashboard


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
    elif reference <= ev.end_time:
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
            "end_time": ev.end_time.isoformat(),
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


# ---------------------------------------------------------------- analysis helpers


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


@router.get("/timeline")
def timeline(
    db: DbSession,
    dataset_id: str,
    event_id: int,
    province_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    replay_mode: Optional[str] = None,
    known_from: Optional[datetime] = None,
    known_to: Optional[datetime] = None,
    limit: int = Query(80, ge=1, le=500),
) -> dict[str, Any]:
    """Event log: official posts, suspension notices and anomalies, each at the time it became known.

    known_from / known_to restrict the log to a window of arrival times (e.g. around the replay cursor)."""
    ctx = _ctx(db, dataset_id, event_id, province_code, as_of=as_of, replay_mode=replay_mode)
    items: list[dict[str, Any]] = []

    def window(q, col):
        if known_from is not None:
            q = q.filter(col.isnot(None), col >= known_from)
        if known_to is not None:
            q = q.filter(col.isnot(None), col <= known_to)
        return q

    oq = (
        db.query(WeiboClean, WeiboRaw)
        .join(WeiboRaw, WeiboRaw.id == WeiboClean.weibo_raw_id)
        .filter(WeiboClean.dataset_id == dataset_id, WeiboClean.event_id == event_id, WeiboClean.account_class == "official")
    )
    if province_code:
        oq = oq.join(WeiboRegion, WeiboRegion.weibo_clean_id == WeiboClean.id).filter(WeiboRegion.province_code == province_code)
    if ctx.strict:
        oq = oq.filter(WeiboClean.available_at.isnot(None), WeiboClean.available_at <= ctx.as_of)
    oq = window(oq, WeiboClean.available_at)
    for wc, raw in oq.order_by(WeiboClean.available_at.desc()).limit(limit):
        items.append(
            {
                "kind": "official_post",
                "time": _iso(raw.published_at),
                "known_at": _iso(wc.available_at),
                "label": mask_text(raw.content)[:60],
                "ref": f"weibo_raw:{raw.id}",
                "province_code": raw.publish_location,
            }
        )
    sq = db.query(TrainSuspension).filter(TrainSuspension.dataset_id == dataset_id, TrainSuspension.event_id == event_id)
    if ctx.strict:
        sq = sq.filter(TrainSuspension.known_at.isnot(None), TrainSuspension.known_at <= ctx.as_of)
    if province_code:
        sq = sq.filter(TrainSuspension.notice_account.like(f"%{province_code}%"))
    sq = window(sq, TrainSuspension.known_at)
    for s in sq.order_by(TrainSuspension.known_at.desc()).limit(limit):
        items.append(
            {
                "kind": "suspension_notice",
                "time": _iso(s.suspension_date),
                "known_at": _iso(s.known_at),
                "label": mask_text(s.evidence_text or s.scope or s.train_code)[:60],
                "ref": f"train_suspension:{s.id}",
                "province_code": None,
            }
        )
    for a in window(anomaly_query(db, ctx), Anomaly.available_at).order_by(Anomaly.hour_bj.desc()).limit(limit):
        items.append(
            {
                "kind": "anomaly",
                "time": a.hour_bj.isoformat(),
                "known_at": _iso(a.available_at),
                "label": a.explanation or a.anomaly_type,
                "ref": f"anomaly:{a.id}",
                "province_code": a.province_code,
            }
        )
    items.sort(key=lambda x: x["known_at"] or x["time"] or "", reverse=True)
    return {"context": ctx.describe(), "items": items[:limit]}


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
