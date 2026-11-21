"""前端契约共用的筛选、计数和时间格式。"""

from datetime import datetime

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Weibo
from app.queries import selection
from app.subjects import metric_counts
from app.timeutil import as_beijing, format_beijing


def fail(code, message, status=422):
    raise HTTPException(status, {"error_code": code, "message": message})


def query_context(
    dataset_id: str,
    event_id: int,
    province_code: str | None = None,
    replay_mode: str = "retrospective",
    as_of: str | None = None,
    data_version: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    stage: str | None = None,
    dimension: str | None = None,
    analysis_scope: str | None = None,
    db: Session = Depends(get_db),
):
    """所有查询与导出共享过滤；未实现的筛选明确拒绝，不静默返回错误口径。"""
    from app.contract_models import ResearchEvent

    event = db.get(ResearchEvent, event_id)
    if not event or event.dataset_id != dataset_id:
        fail("event_not_found", "事件不存在或不属于当前数据集", 404)
    if replay_mode != "retrospective" or as_of:
        fail("replay_not_supported", "MVP 仅支持事后按日查看，不支持当时已知回放")
    if data_version not in (None, "", "current"):
        fail("version_not_supported", "MVP 只查询当前数据，不提供历史版本回放")
    if province_code not in (None, "", "ALL"):
        fail("province_not_supported", "当前为全国口径与起终点示意线，不提供省级小时影响")
    if stage not in (None, "", "灾前", "灾中", "灾后"):
        fail("invalid_stage", "无效灾害阶段")
    if dimension not in (None, "social", "organizational", "physical"):
        fail("invalid_dimension", "无效分析维度")
    if analysis_scope and any(
        item not in ("single", "pair", "joint") for item in analysis_scope.split(",")
    ):
        fail("invalid_scope", "无效分析范围")
    # 研究时间窗口有上下界；单日查询由前端传 00:00:00 至 23:59:59。
    first = as_beijing(start) if start else event.start_time
    last = as_beijing(end) if end else event.end_time
    if first > last:
        fail("invalid_time_range", "开始时间不得晚于结束时间")
    context = {
        "dataset_id": dataset_id,
        "data_mode": "real",
        "event_id": event_id,
        "data_version": "current",
        "active_version": "current",
        "province_code": "ALL",
        "start": format_beijing(first),
        "end": format_beijing(last),
        "as_of": None,
        "replay_mode": "retrospective",
        "analysis_scope": analysis_scope,
        "dimension": dimension,
        "timezone": "Asia/Shanghai",
        "stage": stage or None,
        "stage_applies_to": "weibo_only",
    }
    return event, context


def records(db, query):
    event, context = query
    first = datetime.fromisoformat(context["start"])
    last = datetime.fromisoformat(context["end"])
    posts, rails = selection(db, event.typhoon_id, first.date(), last.date(), context["stage"])
    # 微博可按精确观测时刻过滤；铁路日期不扩展成小时影响。
    posts = posts.where(
        Weibo.published_at >= as_beijing(first),
        Weibo.published_at <= as_beijing(last),
    )
    return db.execute(posts).all(), db.scalars(rails).all()


def counts(posts, rails):
    values = metric_counts(posts)
    values["suspension_count"] = len(rails) if rails else None
    return values
