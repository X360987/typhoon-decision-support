"""数据集、官方目录和研究事件。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.context import fail
from app.contract_models import Dataset, ResearchEvent
from app.db import get_db
from app.models import Typhoon
from app.timeutil import as_beijing, format_beijing, format_utc

router = APIRouter(prefix="/api/v1")


class DatasetInput(BaseModel):
    """建立空的数据集元数据，不生成研究样本。"""

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class EventInput(BaseModel):
    """event_code 必须对应已核对的官方目录，不能任意创建台风。"""

    dataset_id: str
    event_code: str
    name: str | None = None
    start_time: datetime
    end_time: datetime


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": True,
        "error": None,
        "data_mode": "real",
        "write_requires_key": True,
        "seed_allowed": False,
        "time": format_utc(datetime.now(UTC)),
    }


@router.get("/datasets")
def datasets(db: Session = Depends(get_db)):
    return {
        "data_mode": "real",
        "items": [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "data_mode": row.data_mode,
            }
            for row in db.scalars(select(Dataset).order_by(Dataset.id))
        ],
    }


@router.post("/datasets")
def create_dataset(body: DatasetInput, db: Session = Depends(get_db)):
    if db.get(Dataset, body.id):
        fail("duplicate_dataset", "数据集编号已存在", 409)
    db.add(Dataset(**body.model_dump()))
    db.commit()
    return {"id": body.id}


@router.get("/official-typhoons")
def official_catalog(db: Session = Depends(get_db)):
    return {
        "items": [
            {"code": row.id, "name": row.name, "source_url": row.source_url}
            for row in db.scalars(select(Typhoon).order_by(Typhoon.id))
        ]
    }


@router.post("/events")
def create_event(body: EventInput, db: Session = Depends(get_db)):
    if not db.get(Dataset, body.dataset_id):
        fail("dataset_not_found", "数据集不存在", 404)
    official = db.get(Typhoon, body.event_code)
    if not official:
        fail("official_catalog_required", "只能选择官方目录已有台风")
    if body.name and body.name != official.name:
        fail("official_name_mismatch", "名称必须与官方目录一致")
    start, end = as_beijing(body.start_time), as_beijing(body.end_time)
    if end < start:
        fail("invalid_event_window", "事件结束时间不得早于开始时间")
    if db.scalar(select(ResearchEvent).where(ResearchEvent.typhoon_id == official.id)):
        fail("duplicate_event", "该官方台风已注册；MVP 不维护同一台风的多数据集副本", 409)
    event = ResearchEvent(
        dataset_id=body.dataset_id, typhoon_id=official.id, start_time=start, end_time=end
    )
    db.add(event)
    db.commit()
    return {"id": event.id}


@router.get("/events")
def events(dataset_id: str, db: Session = Depends(get_db)):
    if not db.get(Dataset, dataset_id):
        fail("dataset_not_found", "数据集不存在", 404)
    rows = db.execute(
        select(ResearchEvent, Typhoon)
        .join(Typhoon)
        .where(ResearchEvent.dataset_id == dataset_id)
        .order_by(ResearchEvent.id)
    ).all()
    return {
        "items": [
            {
                "id": event.id,
                "dataset_id": dataset_id,
                "event_code": typhoon.id,
                "external_typhoon_id": typhoon.id,
                "name": typhoon.name,
                "start_time": format_beijing(event.start_time),
                "end_time": format_beijing(event.end_time),
                "status": "active",
                "config_version": "mvp-1",
                "active_version": "current",
            }
            for event, typhoon in rows
        ]
    }
