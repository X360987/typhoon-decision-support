"""按日指标、总览和统计导出。"""

import csv
import io
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.context import counts, fail, query_context, records
from app.csvutil import excel_safe
from app.db import get_db
from app.timeutil import TZ

router = APIRouter(prefix="/api/v1")
METRICS = {
    "weibo_count": ("微博总量", "social", "条"),
    "government_weibo_count": ("政府部门发文量", "organizational", "条"),
    "non_government_weibo_count": ("非政府部门发文量", "social", "条"),
    "unclassified_weibo_count": ("政府属性未标注", "social", "条"),
    "suspension_count": ("停运记录", "physical", "车次日"),
}


@router.get("/metrics/registry")
def registry():
    return {
        "rule_version": "mvp-1",
        "rules": {},
        "items": [
            {
                "id": key,
                "name": name,
                "dimension": dimension,
                "unit": unit,
                "aggregation": "daily_count",
                "description": "按日统计；缺失不填零",
                "numerator": None,
                "denominator": None,
                "dedup_key": "platform_id"
                if dimension != "physical"
                else "event+departure_date+train",
                "national_rule": "ALL，原始记录去重；不从省份求和",
                "version": "mvp-1",
            }
            for key, (name, dimension, unit) in METRICS.items()
        ],
    }


@router.get("/metrics/series")
def series(metric_id: str | None = None, q=Depends(query_context), db: Session = Depends(get_db)):
    requested = metric_id.split(",") if metric_id else list(METRICS)
    if any(key not in METRICS for key in requested):
        fail("unknown_metric", "指标不在 MVP 注册表内；不将个人/官方替代政府/非政府")
    posts, rails = records(db, q)
    grouped_posts, grouped_rail = {}, {}
    for post, event in posts:
        grouped_posts.setdefault(post.published_at.astimezone(TZ).date(), []).append((post, event))
    for row in rails:
        grouped_rail.setdefault(row.departure_date, []).append(row)
    items = []
    for day in sorted(set(grouped_posts) | set(grouped_rail)):
        values = counts(grouped_posts.get(day, []), grouped_rail.get(day, []))
        for key in requested:
            items.append(
                {
                    "province_code": "ALL",
                    "hour_bj": day.isoformat() + "T00:00:00",
                    "metric_id": key,
                    "value": values[key],
                    "sample_size": values[key],
                    "coverage": None,
                    "quality_status": "observed" if values[key] is not None else "missing",
                    "unit": METRICS[key][2],
                    "version": "current",
                    "available_at": None,
                }
            )
    return {
        "context": q[1],
        "granularity": "day",
        "strict_unavailable": 0,
        "coverage_status": "not_verified",
        "items": items,
    }


@router.get("/dashboard/summary")
def summary(q=Depends(query_context), db: Session = Depends(get_db)):
    posts, rails = records(db, q)
    cards = {
        key: {
            "metric_id": key,
            "name": METRICS[key][0],
            "unit": METRICS[key][2],
            "hour_bj": q[1]["end"],
            "provinces": {"ALL": value},
            "value": value,
            "sample_size": value,
            "aggregation": "selected_range_count",
            "quality": "ok" if value is not None else "insufficient",
        }
        for key, value in counts(posts, rails).items()
    }
    return {
        "context": q[1],
        "data_mode": "real",
        "empty": not posts and not rails,
        "cards": cards,
        "message": "缺失数据不填零；铁路单位为车次日；阶段仅筛选微博",
        "coverage_status": "not_verified",
    }


@router.get("/export/{kind}")
def export(
    kind: Literal["metrics", "anomalies"], q=Depends(query_context), db: Session = Depends(get_db)
):
    """浏览器直接下载，无 API Key；复用相同查询上下文。"""
    if kind == "anomalies":
        fail("analysis_not_integrated", "算法尚未接入，无异常结果可导出", 409)
    data = series(None, q, db)
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(
        [
            "dataset_id",
            "event_id",
            "data_version",
            "date_bj",
            "metric_id",
            "value",
            "unit",
            "quality_status",
        ]
    )
    for row in data["items"]:
        values = [
            q[1]["dataset_id"],
            q[1]["event_id"],
            "current",
            row["hour_bj"][:10],
            row["metric_id"],
            row["value"],
            row["unit"],
            row["quality_status"],
        ]
        writer.writerow([excel_safe(value) for value in values])
    return Response(
        out.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="metrics.csv"'},
    )
