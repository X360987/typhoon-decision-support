"""日期筛选和起终点示意线。早期接口与前端契约共用，避免两套口径。"""

from collections import Counter
from datetime import datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.geo import endpoints
from app.models import EventPost, ImportBatch, ManualSuspension, Station, Suspension, Typhoon, Weibo
from app.timeutil import TZ


def require_event(db, event_id):
    if not db.get(Typhoon, event_id):
        raise HTTPException(404, "台风不在已导入官方目录中")


def selection(db, event_id, start_date, end_date, stage=None):
    """统一日期包含边界。阶段只筛选微博。

    该事件一旦有人工长表，铁路统计只读人工长表，不再混入公告明细。
    """
    require_event(db, event_id)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "开始日期不得晚于结束日期")
    if stage not in {None, "灾前", "灾中", "灾后"}:
        raise HTTPException(422, "无效灾害阶段")
    posts = (
        select(Weibo, EventPost)
        .join(EventPost, EventPost.weibo_id == Weibo.id)
        .where(EventPost.typhoon_id == event_id)
    )
    manual = db.scalar(
        select(ManualSuspension.record_id).where(ManualSuspension.typhoon_id == event_id).limit(1)
    )
    rail_model = ManualSuspension if manual is not None else Suspension
    rail = select(rail_model).where(rail_model.typhoon_id == event_id)
    if start_date:
        posts = posts.where(Weibo.published_at >= datetime.combine(start_date, time.min, TZ))
        rail = rail.where(rail_model.departure_date >= start_date)
    if end_date:
        posts = posts.where(
            Weibo.published_at < datetime.combine(end_date + timedelta(days=1), time.min, TZ)
        )
        rail = rail.where(rail_model.departure_date <= end_date)
    if stage:
        posts = posts.where(EventPost.stage == stage)
    return posts, rail


def availability(db, event_id, kind, count):
    """导入历史不等于覆盖完整；无记录不宣称真实停运数量为零。"""
    batches = db.scalar(
        select(func.count())
        .select_from(ImportBatch)
        .where(
            ImportBatch.typhoon_id == event_id,
            ImportBatch.kind.in_(("rail", "rail_manual") if kind == "rail" else (kind,)),
            ImportBatch.status == "committed",
        )
    )
    state = "available" if count else ("no_records_in_selection" if batches else "not_imported")
    return {
        "state": state,
        "coverage": "not_verified",
        "count": count if batches or count else None,
    }


def _coordinates_ready(origin, destination):
    if origin is None or destination is None:
        return False
    return all(
        v is not None
        for v in (origin.longitude, origin.latitude, destination.longitude, destination.latitude)
    )


def map_data(rows, db: Session):
    """按方向合并端点示意线。任一端没有站名或坐标时不生成路线。"""
    stations = {s.name: s for s in db.scalars(select(Station))}
    counts, points = Counter(), {}
    for row in rows:
        origin_name, destination_name = endpoints(row)
        origin, destination = stations.get(origin_name), stations.get(destination_name)
        if not _coordinates_ready(origin, destination):
            continue
        counts[(origin.name, destination.name)] += 1
        for station in (origin, destination):
            points[station.name] = {
                "name": station.name,
                "longitude": station.longitude,
                "latitude": station.latitude,
            }
    located = sum(counts.values())
    return {
        "points": list(points.values()),
        "lines": [
            {"origin": origin, "destination": destination, "count": n}
            for (origin, destination), n in sorted(counts.items())
        ],
        "total": len(rows),
        "locatable": located,
        "unlocated": len(rows) - located,
        "geometry_kind": "schematic",
        "crs": "WGS84",
    }
