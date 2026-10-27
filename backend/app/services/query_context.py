"""Shared query context so every list, card, chart, detail and export applies the same filters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, or_
from sqlalchemy.orm import Query, Session

from app.models import Anomaly, Dataset, Event, ProvinceHourMetric
from app.services.pipeline import NATIONAL, get_active_version

REPLAY_MODES = ("as_known", "retrospective")
SCOPES = ("single", "pair", "joint")
DIMENSIONS = ("social", "organizational", "physical")


@dataclass
class QueryContext:
    dataset: Dataset
    event: Event
    data_version: str
    active_version: str
    province_code: str | None
    start: datetime | None
    end: datetime | None
    as_of: datetime | None
    replay_mode: str
    analysis_scope: str | None
    dimension: str | None

    @property
    def dataset_id(self) -> str:
        return self.dataset.id

    @property
    def event_id(self) -> int:
        return self.event.id

    @property
    def strict(self) -> bool:
        return self.replay_mode == "as_known" and self.as_of is not None

    def describe(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "data_mode": self.dataset.data_mode,
            "event_id": self.event_id,
            "data_version": self.data_version,
            "active_version": self.active_version,
            "province_code": self.province_code,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "replay_mode": self.replay_mode,
            "analysis_scope": self.analysis_scope,
            "dimension": self.dimension,
            "timezone": "Asia/Shanghai (北京时间，存储为无时区时间)",
        }

    def summary_text(self) -> str:
        parts = [
            f"数据集={self.dataset_id}({self.dataset.data_mode})",
            f"事件={self.event.event_code}",
            f"版本={self.data_version}",
            f"省份={self.province_code or '全部'}",
            f"模式={'当时已知' if self.replay_mode == 'as_known' else '事后复盘'}",
        ]
        if self.as_of:
            parts.append(f"as_of={self.as_of.isoformat()}")
        if self.start or self.end:
            parts.append(f"时段={self.start.isoformat() if self.start else ''}~{self.end.isoformat() if self.end else ''}")
        if self.analysis_scope:
            parts.append(f"范围={self.analysis_scope}")
        if self.dimension:
            parts.append(f"维度={self.dimension}")
        return "; ".join(parts)


def _bad(message: str, code: str = "bad_request", status: int = 400) -> HTTPException:
    return HTTPException(status, detail={"error_code": code, "message": message})


def resolve_context(
    db: Session,
    dataset_id: str,
    event_id: int,
    *,
    province_code: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    as_of: datetime | None = None,
    replay_mode: str | None = None,
    data_version: str | None = None,
    analysis_scope: str | None = None,
    dimension: str | None = None,
) -> QueryContext:
    from app.api.deps import readable_dataset

    ds = readable_dataset(db, dataset_id)
    ev = db.get(Event, event_id)
    if not ev or ev.dataset_id != dataset_id:
        raise _bad("事件不存在或不属于该数据集", "not_found", 404)
    mode = replay_mode or ("as_known" if as_of else "retrospective")
    if mode not in REPLAY_MODES:
        raise _bad(f"replay_mode 仅支持 {REPLAY_MODES}")
    if mode == "as_known" and as_of is None:
        raise _bad("当时已知模式需要 as_of")
    if analysis_scope and any(s not in SCOPES for s in analysis_scope.split(",")):
        raise _bad(f"analysis_scope 仅支持 {SCOPES}（可用逗号组合）")
    if dimension and dimension not in DIMENSIONS:
        raise _bad(f"dimension 仅支持 {DIMENSIONS}")
    active = get_active_version(db, dataset_id, event_id)
    return QueryContext(
        dataset=ds,
        event=ev,
        data_version=data_version or active,
        active_version=active,
        province_code=province_code or None,
        start=start,
        end=end,
        as_of=as_of,
        replay_mode=mode,
        analysis_scope=analysis_scope,
        dimension=dimension,
    )


def metric_query(db: Session, ctx: QueryContext, include_national: bool = False) -> Query:
    q = db.query(ProvinceHourMetric).filter(
        ProvinceHourMetric.dataset_id == ctx.dataset_id,
        ProvinceHourMetric.event_id == ctx.event_id,
        ProvinceHourMetric.version == ctx.data_version,
    )
    if ctx.province_code:
        q = q.filter(ProvinceHourMetric.province_code == ctx.province_code)
    elif not include_national:
        q = q.filter(ProvinceHourMetric.province_code != NATIONAL)
    if ctx.start:
        q = q.filter(ProvinceHourMetric.hour_bj >= ctx.start)
    if ctx.end:
        q = q.filter(ProvinceHourMetric.hour_bj <= ctx.end)
    return q


def visible_metrics(db: Session, ctx: QueryContext, q: Query) -> tuple[list[ProvinceHourMetric], int]:
    """Apply as_known availability. Returns (rows, rows hidden because arrival time is unknown)."""
    if not ctx.strict:
        return q.order_by(ProvinceHourMetric.hour_bj).all(), 0
    unknown = q.filter(
        ProvinceHourMetric.available_at.is_(None), ProvinceHourMetric.hour_bj < ctx.as_of
    ).count()
    rows = (
        q.filter(ProvinceHourMetric.available_at.isnot(None), ProvinceHourMetric.available_at <= ctx.as_of)
        .order_by(ProvinceHourMetric.hour_bj)
        .all()
    )
    return rows, unknown


def anomaly_query(db: Session, ctx: QueryContext, apply_availability: bool = True) -> Query:
    q = db.query(Anomaly).filter(
        Anomaly.dataset_id == ctx.dataset_id,
        Anomaly.event_id == ctx.event_id,
        Anomaly.data_version == ctx.data_version,
    )
    if ctx.analysis_scope:
        q = q.filter(Anomaly.analysis_scope.in_(ctx.analysis_scope.split(",")))
    if ctx.province_code:
        q = q.filter(Anomaly.province_code == ctx.province_code)
    if ctx.dimension:
        q = q.filter(
            or_(
                Anomaly.dims_key.like(f"%,{ctx.dimension},%"),
                and_(Anomaly.dims_key.is_(None), cast(Anomaly.dimensions, String).like(f'%"{ctx.dimension}"%')),
            )
        )
    if ctx.start:
        q = q.filter(Anomaly.hour_bj >= ctx.start)
    if ctx.end:
        q = q.filter(Anomaly.hour_bj <= ctx.end)
    if apply_availability and ctx.strict:
        q = q.filter(Anomaly.available_at.isnot(None), Anomaly.available_at <= ctx.as_of)
    return q


def pending_anomaly_count(db: Session, ctx: QueryContext) -> int:
    """Lagged relations whose window has not matured at as_of."""
    if not ctx.strict:
        return 0
    return (
        anomaly_query(db, ctx, apply_availability=False)
        .filter(
            Anomaly.requires_future_window.is_(True),
            Anomaly.hour_bj <= ctx.as_of,
            Anomaly.available_at > ctx.as_of,
        )
        .count()
    )


def card_hour(ctx: QueryContext, hour_bj: datetime | None) -> datetime:
    """Hour shown on cards: the last complete hour before as_of when replaying as known."""
    if ctx.strict:
        return ctx.as_of.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    return hour_bj or ctx.as_of or ctx.event.start_time
