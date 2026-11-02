"""场景：灾后。回放时间线与资料导出。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import PlainTextResponse

from app.api.common import _ctx, _iso
from app.api.deps import DbSession
from app.models import Anomaly, TrainSuspension, WeiboClean, WeiboRaw, WeiboRegion
from app.services.export_service import export_anomalies_csv, export_metrics_csv
from app.services.pipeline import mask_text
from app.services.query_context import anomaly_query

router = APIRouter()

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
