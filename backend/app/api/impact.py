"""停运明细、按日数量和起终点示意线。

人工长表目前没有站名，可定位数为 0 是预期结果。
2023 年车次对照接入 `app.geo.endpoints` 之后，在本路由按日期补充各站始发数、终到数和未定位数。
站名和坐标的判断不要写在这里。
"""

from collections import Counter

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.context import query_context, records
from app.db import get_db
from app.geo import count_endpoints, endpoints
from app.models import ManualSuspension, Train
from app.queries import map_data

router = APIRouter(prefix="/api/v1")


@router.get("/impact")
def impact(q=Depends(query_context), db: Session = Depends(get_db)):
    _, rails = records(db, q)
    train_names = {row.id: row.train_no for row in db.scalars(select(Train))}
    origins, destinations = count_endpoints(rails)
    daily = Counter(row.departure_date.isoformat() for row in rails)
    return {
        "context": q[1],
        **map_data(rails, db),
        "granularity": "day",
        "unit": "车次日",
        "daily": [{"date": day, "count": n} for day, n in sorted(daily.items())],
        "origins": origins,
        "destinations": destinations,
        "suspensions": [_suspension(row, train_names) for row in rails],
    }


def _suspension(row, train_names):
    origin, destination = endpoints(row)
    manual = isinstance(row, ManualSuspension)
    return {
        "id": row.record_id,
        "train_code": row.raw_train_no if manual else train_names[row.train_id],
        "source_kind": "rail_manual" if manual else "rail",
        "suspension_date": row.departure_date.isoformat(),
        "segment": [origin, destination],
        "source_weibo_id": row.source_weibo_id,
        "scope": row.scope,
    }
