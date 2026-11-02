"""场景：复用。路由共用的错误体、时间、查询上下文和请求体。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from app.models import Anomaly, ReviewRecord
from app.services.query_context import QueryContext, resolve_context

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
    english_name: Optional[str] = None
    aliases: Optional[list[str]] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "tracking"
    warning_level: Optional[str] = None
    forecast_provinces: Optional[list[str]] = None
    source_mode: str = "manual"
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
