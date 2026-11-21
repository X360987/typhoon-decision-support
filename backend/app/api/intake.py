"""前端契约的两步导入：预检凭证、提交、批次和错误。"""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.context import fail
from app.attitude import NOT_INTEGRATED
from app.config import settings
from app.contract_models import Dataset, ImportTicket, ResearchEvent
from app.db import get_db
from app.importers.batch import preview_upload
from app.importers.processor import ImportProcessor
from app.models import ImportBatch
from app.timeutil import format_utc

router = APIRouter(prefix="/api/v1")


@router.get("/import/sources")
def import_sources():
    return {
        "items": [
            {"entity": key, "name": name, "status": "supported"}
            for key, name in [
                ("weibo", "微博数据"),
                ("rail", "铁路全程停运"),
                ("rail_manual", "人工停运工作簿（ID_type长表）"),
                ("trains", "年度车次目录"),
                ("stations", "车站坐标"),
            ]
        ],
        "max_upload_mb": settings.max_upload_bytes // (1024 * 1024),
    }


def _event_for_import(db, dataset_id, event_id):
    event = db.get(ResearchEvent, event_id)
    if not event or event.dataset_id != dataset_id:
        fail("event_not_found", "事件不存在或不属于数据集", 404)
    return event


def _preview_report(batch, ticket):
    report = batch.report
    errors = report["errors"]
    changes = [item for item in report["warnings"] if "decision_token" in item]
    error_rows = [
        {
            "row": err["row"],
            "reasons": [err["reason"]],
            "blocking": True,
            "duplicate": False,
            "train_no": err.get("train_no"),
            "conflicts": err.get("conflicts"),
        }
        for err in errors
    ]
    return {
        "ok": True,
        "entity": batch.kind,
        "rows": len(batch.rows),
        "columns": list(batch.rows[0]) if batch.rows else [],
        "error_rows": error_rows,
        "blocking_errors": len(errors),
        "duplicates": report["duplicates"],
        "warnings": len(report["warnings"]),
        "warning_details": report["warnings"],
        "identity_changes": changes,
        "time_range": None,
        "province_coverage": {},
        "checks": [],
        "preview": [
            {
                "row": row["_row"],
                "content": str(
                    row.get("微博正文", row.get("text", row.get("标准车次", row.get("车次", ""))))
                ),
                "status": "error"
                if any(
                    err["row"] == row["_row"] and err["sheet"] == row["_sheet"] for err in errors
                )
                else "ok",
                "published_at": row.get("发布时间"),
                "publish_location": row.get("发布位置"),
            }
            for row in batch.rows[:30]
        ],
        "precheck_token": ticket.token,
        "allowed_policies": ["strict", "skip_errors"],
        "file_name": batch.filename,
        "batch_id": ticket.id,
        "inserted": report["inserted"],
        "updated": report["updated"],
    }


@router.post("/import/precheck")
def precheck(
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    event_id: int = Form(...),
    entity: Literal["weibo", "rail", "rail_manual", "trains", "stations"] = Form(...),
    catalog_year: int | None = Form(None),
    db: Session = Depends(get_db),
):
    event = _event_for_import(db, dataset_id, event_id)
    result = preview_upload(entity, file, event.typhoon_id, catalog_year, db)
    batch = db.get(ImportBatch, result["batch_id"])
    fingerprint = hashlib.sha256(
        f"mvp-1|{dataset_id}|{event_id}|{entity}|{catalog_year}|{batch.sha256}".encode()
    ).hexdigest()
    ticket = ImportTicket(
        token=secrets.token_urlsafe(32),
        event_id=event_id,
        batch_id=batch.id,
        fingerprint=fingerprint,
    )
    db.add(ticket)
    db.commit()
    return _preview_report(batch, ticket)


@router.post("/import/commit")
def commit_file(
    file: UploadFile = File(...),
    dataset_id: str = Form(...),
    event_id: int = Form(...),
    precheck_token: str = Form(...),
    error_policy: Literal["strict", "skip_errors"] = Form("skip_errors"),
    confirm_skip: bool = Form(False),
    decisions: str = Form("{}"),
    db: Session = Depends(get_db),
):
    """同文件同事件同类别复用成功批次；拒绝换文件、换事件或过期凭证。"""
    _event_for_import(db, dataset_id, event_id)
    ticket = db.scalar(select(ImportTicket).where(ImportTicket.token == precheck_token))
    if not ticket or ticket.event_id != event_id:
        fail("invalid_precheck_token", "预检凭证无效或不属于当前事件")
    batch = db.get(ImportBatch, ticket.batch_id)
    content = file.file.read(settings.max_upload_bytes + 1)
    if hashlib.sha256(content).hexdigest() != batch.sha256:
        fail("file_changed", "提交文件与预检文件不同，请重新预检")
    try:
        choices = json.loads(decisions)
        if not isinstance(choices, dict) or any(
            type(value) is not bool for value in choices.values()
        ):
            raise ValueError()
    except (ValueError, TypeError):
        fail("invalid_decisions", "身份确认必须是令牌到布尔值的 JSON 对象")
    # 同一把锁覆盖幂等检查和写入，两个并发凭证不会重复处理相同文件。
    db.execute(text("SELECT pg_advisory_xact_lock(782301)"))
    previous = db.execute(
        select(ImportTicket, ImportBatch)
        .join(ImportBatch)
        .where(ImportTicket.fingerprint == ticket.fingerprint, ImportBatch.status == "committed")
        .order_by(ImportTicket.id)
    ).first()
    if previous:
        db.commit()
        return {
            "ok": True,
            "import_status": "idempotent_reuse",
            "analysis_status": NOT_INTEGRATED,
            "batch_id": previous[0].id,
            "inserted": previous[1].report["inserted"],
            "skipped": previous[1].report["error_count"] + previous[1].report["duplicates"],
        }
    if datetime.now(UTC) - ticket.created_at > timedelta(hours=24):
        fail("precheck_expired", "预检凭证超过 24 小时，请重新预检")
    savepoint = db.begin_nested()
    try:
        report = ImportProcessor(db, batch, choices).run()
        if report["errors"] and (error_policy == "strict" or not confirm_skip):
            savepoint.rollback()
            fail("import_errors", "存在错误行；请修改文件或明确选择跳过错误后提交")
        savepoint.commit()
        batch.report = report
        batch.status = "committed"
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "ok": True,
        "import_status": "imported",
        "analysis_status": NOT_INTEGRATED,
        "batch_id": ticket.id,
        "inserted": report["inserted"],
        "updated": report["updated"],
        "skipped": report["error_count"] + report["duplicates"],
        "excluded_rows": report["errors"],
    }


@router.get("/import/batches")
def batches(dataset_id: str, db: Session = Depends(get_db)):
    if not db.get(Dataset, dataset_id):
        fail("dataset_not_found", "数据集不存在", 404)
    rows = db.execute(
        select(ImportTicket, ImportBatch)
        .join(ImportBatch)
        .join(ResearchEvent, ResearchEvent.id == ImportTicket.event_id)
        .where(ResearchEvent.dataset_id == dataset_id)
        .order_by(ImportTicket.id.desc())
    ).all()
    return {
        "items": [
            {
                "id": ticket.id,
                "event_id": ticket.event_id,
                "file_name": batch.filename,
                "source_type": batch.kind,
                "status": batch.status,
                "created_at": format_utc(batch.created_at),
                "report": batch.report,
            }
            for ticket, batch in rows
        ]
    }


@router.get("/import/errors/{batch_id}")
def import_errors(batch_id: int, dataset_id: str, db: Session = Depends(get_db)):
    ticket = db.get(ImportTicket, batch_id)
    if not ticket:
        fail("batch_not_found", "批次不存在", 404)
    _event_for_import(db, dataset_id, ticket.event_id)
    batch = db.get(ImportBatch, ticket.batch_id)
    return {
        "batch_id": batch_id,
        "status": batch.status,
        "items": [
            {"row_number": err["row"], "reason": err["reason"], "raw_payload": err}
            for err in batch.report["errors"]
        ],
    }
