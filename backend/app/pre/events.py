"""场景：灾前。手动登记与按台风编号合并。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Event


class EventConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def register_or_merge(db: Session, fields: dict[str, Any]) -> tuple[Event, bool]:
    """Same typhoon id updates the existing event. A different event code still conflicts."""
    dataset_id = fields["dataset_id"]
    typhoon_id = fields.get("external_typhoon_id") or None
    code = fields["event_code"]
    by_code = db.query(Event).filter(Event.dataset_id == dataset_id, Event.event_code == code).first()
    by_typhoon = None
    if typhoon_id:
        by_typhoon = (
            db.query(Event)
            .filter(Event.dataset_id == dataset_id, Event.external_typhoon_id == typhoon_id)
            .first()
        )
    target = by_typhoon or by_code
    if by_code and by_typhoon and by_code.id != by_typhoon.id:
        raise EventConflict("event_exists", "事件编号与台风编号分别对应已有事件，不能合并")
    if target and not by_typhoon and by_code:
        raise EventConflict("event_exists", "事件已存在")
    merged = target is not None
    event = target or Event(dataset_id=dataset_id, event_code=code)
    event.name = fields["name"]
    event.external_typhoon_id = typhoon_id
    event.english_name = fields.get("english_name")
    event.aliases = fields.get("aliases")
    event.start_time = fields["start_time"]
    if "end_time" in fields:
        event.end_time = fields.get("end_time")
    event.status = fields.get("status") or event.status or "tracking"
    event.warning_level = fields.get("warning_level")
    event.forecast_provinces = fields.get("forecast_provinces")
    event.source_mode = fields.get("source_mode") or event.source_mode or "manual"
    event.config_version = fields.get("config_version") or event.config_version or "v1"
    if not merged:
        db.add(event)
    db.flush()
    return event, merged
