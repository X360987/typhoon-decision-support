"""场景：灾前。事件登记与文件导入。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.common import EventCreate, _ctx, _err, _utc_iso
from app.api.deps import DbSession, WriteOperator, readable_dataset, writable_dataset
from app.config import get_settings
from app.models import CollectionTask, DataBatch, Event, ImportErrorRow, KeywordSet
from app.services.bootstrap import ensure_dataset
from app.services.demo_setup import seed_and_prepare_demo
from app.services.import_service import (
    ALLOWED_SUFFIXES,
    IMPORT_SOURCES,
    ImportRejected,
    commit_weibo_import,
    precheck,
)
from app.pre.cma import sync_cma_events
from app.pre.events import EventConflict, register_or_merge
from app.pre.keywords import build_keyword_set, estimate_coverage
from app.services.pipeline import get_active_version

router = APIRouter()

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
                "end_time": e.end_time.isoformat() if e.end_time else None,
                "status": e.status,
                "warning_level": e.warning_level,
                "forecast_provinces": e.forecast_provinces,
                "source_mode": e.source_mode,
                "english_name": e.english_name,
                "config_version": e.config_version,
                "active_version": get_active_version(db, dataset_id, e.id),
            }
            for e in rows
        ]
    }


@router.post("/events")
def create_event(body: EventCreate, db: DbSession, operator: WriteOperator) -> dict[str, Any]:
    settings = get_settings()
    if body.end_time is not None and body.end_time <= body.start_time:
        raise _err(400, "bad_time_range", "结束时间必须晚于开始时间")
    if writable_dataset(db, body.dataset_id, allow_create=True) is None:
        ensure_dataset(db, body.dataset_id, settings.data_mode)
    try:
        event, merged = register_or_merge(db, body.model_dump())
    except EventConflict as exc:
        raise _err(409, exc.code, exc.message) from exc
    db.commit()
    db.refresh(event)
    return {"id": event.id, "merged": merged, "operator": operator}


@router.post("/events/sync")
def sync_events(db: DbSession, operator: WriteOperator, dataset_id: str = Query(...)) -> dict[str, Any]:
    settings = get_settings()
    if writable_dataset(db, dataset_id, allow_create=True) is None:
        ensure_dataset(db, dataset_id, settings.data_mode)
    try:
        result = sync_cma_events(db, dataset_id)
    except Exception as exc:  # noqa: BLE001
        raise _err(502, "cma_unavailable", f"中央气象台台风网暂时无法读取: {exc}") from exc
    return {**result, "operator": operator}


@router.post("/events/{event_id}/keywords")
def build_event_keywords(event_id: int, db: DbSession, operator: WriteOperator, dataset_id: str = Query(...)) -> dict[str, Any]:
    writable_dataset(db, dataset_id)
    event = db.get(Event, event_id)
    if event is None or event.dataset_id != dataset_id:
        raise _err(404, "not_found", "事件不存在或不属于该数据集")
    built = build_keyword_set(
        name=event.name,
        english_name=event.english_name,
        typhoon_id=event.external_typhoon_id,
        aliases=event.aliases or [],
        provinces=event.forecast_provinces or [],
    )
    current = (
        db.query(KeywordSet)
        .filter(KeywordSet.dataset_id == dataset_id, KeywordSet.event_id == event.id)
        .order_by(KeywordSet.version.desc())
        .first()
    )
    version = 1 if current is None else current.version + 1
    row = KeywordSet(
        dataset_id=dataset_id,
        event_id=event.id,
        version=version,
        keywords=built["keywords"],
        negative_keywords=built["negative_keywords"],
        coverage=estimate_coverage(built["keywords"], built["negative_keywords"], []),
    )
    db.add(row)
    db.add(
        CollectionTask(
            dataset_id=dataset_id,
            event_id=event.id,
            keyword_version=version,
            status="planned",
            window_start=event.start_time,
            window_end=event.end_time,
            query_text=" OR ".join(built["keywords"]),
        )
    )
    db.commit()
    return {"version": version, "keywords": built["keywords"], "negative_keywords": built["negative_keywords"], "operator": operator}
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
    entity: str = Form("weibo"),
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
            entity=entity,
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
