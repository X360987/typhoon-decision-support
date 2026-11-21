"""早期按台风编号的查询和预览。新功能加在前端契约路由，不要加在这里。"""

import csv
import io
import logging
from collections import Counter
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.attitude import legacy_status
from app.csvutil import excel_safe
from app.db import get_db
from app.geo import count_endpoints
from app.importers.batch import preview_upload
from app.importers.processor import ImportProcessor
from app.models import EventPost, ImportBatch, ManualSuspension, Suspension, Typhoon
from app.queries import availability, map_data, require_event, selection
from app.subjects import overview_counts
from app.timeutil import TZ

router = APIRouter()
log = logging.getLogger(__name__)


class CommitRequest(BaseModel):
    """账号敏感属性的确认令牌，未同意的变化不覆盖当前账号资料。"""

    decisions: dict[str, bool] = Field(default_factory=dict)


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """探测真实数据库连接，失败返回 503，不伪装为健康。"""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        log.exception("数据库健康检查失败")
        raise HTTPException(503, "数据库不可用") from None
    return {"status": "ok", "database": "postgresql"}


@router.post("/api/v1/imports/preview")
def preview(
    kind: Literal["weibo", "rail", "rail_manual", "trains", "stations"] = Form(...),
    file: UploadFile = File(...),
    typhoon_id: str | None = Form(None),
    catalog_year: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """保存原始文件及预览；所有试写业务记录在返回前回滚。"""
    return preview_upload(kind, file, typhoon_id, catalog_year, db)


@router.post("/api/v1/imports/{batch_id}/commit")
def commit(batch_id: str, body: CommitRequest, db: Session = Depends(get_db)):
    """串行化本地导入提交并重新校验，防止并发覆盖与重复计数。"""
    db.execute(text("SELECT pg_advisory_xact_lock(782301)"))
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "导入批次不存在")
    if batch.status == "committed":
        return {"batch_id": batch.id, "status": batch.status, **batch.report}
    try:
        batch.report = ImportProcessor(db, batch, body.decisions).run()
        batch.status = "committed"
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "数据关联或唯一性冲突，本次事务已回滚；请重新预览") from None
    return {"batch_id": batch.id, "status": batch.status, **batch.report}


@router.get("/api/v1/imports/{batch_id}")
def batch_result(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(404, "导入批次不存在")
    return {"batch_id": batch.id, "kind": batch.kind, "status": batch.status, **batch.report}


@router.get("/api/v1/imports/{batch_id}/errors")
def batch_errors(batch_id: str, db: Session = Depends(get_db)):
    result = batch_result(batch_id, db)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(["行号", "工作表", "拆分车次", "原因", "冲突详情"])
    for err in result["errors"]:
        cells = [
            err["row"],
            err["sheet"],
            err["train_no"] or "",
            err["reason"],
            str(err.get("conflicts", "")),
        ]
        writer.writerow([excel_safe(cell) for cell in cells])
    return Response(
        out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-errors.csv"'},
    )


@router.get("/api/v1/typhoons")
def typhoons(db: Session = Depends(get_db)):
    ids = set(db.scalars(select(EventPost.typhoon_id)).all()) | set(
        db.scalars(select(Suspension.typhoon_id)).all()
    )
    ids.update(db.scalars(select(ManualSuspension.typhoon_id).distinct()))
    return [
        {"id": t.id, "name": t.name, "source_url": t.source_url, "has_data": t.id in ids}
        for t in db.scalars(select(Typhoon).order_by(Typhoon.id))
    ]


@router.get("/api/v1/typhoons/{event_id}/filters")
def filters(event_id: str, db: Session = Depends(get_db)):
    posts, rail = selection(db, event_id, None, None)
    published = db.execute(posts).all()
    suspensions = db.scalars(rail).all()
    dates = {row.published_at.astimezone(TZ).date().isoformat() for row, _ in published} | {
        row.departure_date.isoformat() for row in suspensions
    }
    return {
        "dates_with_records": sorted(dates),
        "start_date": min(dates) if dates else None,
        "end_date": max(dates) if dates else None,
        "stages": sorted({event.stage for _, event in published if event.stage}),
        "coverage": "not_verified",
    }


@router.get("/api/v1/typhoons/{event_id}/overview")
def overview(
    event_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    db: Session = Depends(get_db),
):
    posts_query, rails_query = selection(db, event_id, start_date, end_date, stage)
    posts, rails = db.execute(posts_query).all(), db.scalars(rails_query).all()
    return {
        "weibo": availability(db, event_id, "weibo", len(posts)),
        "rail": availability(db, event_id, "rail", len(rails)),
        **overview_counts(posts),
        "rail_unit": "车次日",
        "stage_applies_to": "weibo_only",
    }


@router.get("/api/v1/typhoons/{event_id}/social/statistics")
def social(
    event_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    stage: str | None = None,
    db: Session = Depends(get_db),
):
    posts_query, _ = selection(db, event_id, start_date, end_date, stage)
    posts = db.execute(posts_query).all()
    daily = Counter(row.published_at.astimezone(TZ).date().isoformat() for row, _ in posts)
    heats = [row.heat for row, _ in posts if row.heat is not None]
    return {
        "daily": [{"date": day, "count": n} for day, n in sorted(daily.items())],
        "heat_sum": sum(heats) if heats else None,
        "heat_sample_count": len(heats),
        "status": availability(db, event_id, "weibo", len(posts)),
    }


@router.get("/api/v1/typhoons/{event_id}/rail/statistics")
def rail_stats(
    event_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    _, rails_query = selection(db, event_id, start_date, end_date)
    rows = db.scalars(rails_query).all()
    daily = Counter(row.departure_date.isoformat() for row in rows)
    origins, destinations = count_endpoints(rows)
    located = map_data(rows, db)["locatable"]
    return {
        "daily": [{"date": day, "count": n} for day, n in sorted(daily.items())],
        "origins": origins,
        "destinations": destinations,
        "total": len(rows),
        "locatable": located,
        "unit": "车次日",
        "status": availability(db, event_id, "rail", len(rows)),
    }


@router.get("/api/v1/typhoons/{event_id}/rail/map")
def rail_map(
    event_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    _, rails_query = selection(db, event_id, start_date, end_date)
    return map_data(db.scalars(rails_query).all(), db)


@router.get("/api/v1/typhoons/{event_id}/social/analysis")
def pending_analysis(event_id: str, db: Session = Depends(get_db)):
    """算法契约未明确时返回未接入，不把空结果写成分析结果。"""
    require_event(db, event_id)
    return legacy_status()
