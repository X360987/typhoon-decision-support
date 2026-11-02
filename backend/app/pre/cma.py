"""场景：灾前。读取中央气象台台风网的台风列表与预警，并保存来源快照。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.models import Event, SourceSnapshot, WarningRecord
from app.pre.events import register_or_merge

LIST_URL = "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/list_default"
VIEW_URL = "http://typhoon.nmc.cn/weatherservice/typhoon/jsons/view_{typhoon_id}"


def unwrap_jsonp(text: str) -> Any:
    raw = text.strip()
    start = raw.find("(")
    end = raw.rfind(")")
    if start != -1 and end > start and not raw.startswith("{"):
        raw = raw[start + 1 : end]
    return json.loads(raw)


def _text_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", ""))
    except ValueError:
        return None


def parse_typhoon_list(text: str) -> list[dict[str, Any]]:
    data = unwrap_jsonp(text)
    rows = data.get("typhoonList") if isinstance(data, dict) else data
    out: list[dict[str, Any]] = []
    for item in rows or []:
        if isinstance(item, dict):
            typhoon_id = str(item.get("tfid") or item.get("id") or item.get("typhoon_id") or "")
            name = item.get("name") or item.get("name_cn") or typhoon_id
            english = item.get("enname") or item.get("name_en")
            start = _text_time(item.get("starttime") or item.get("start_time"))
        elif isinstance(item, list) and len(item) >= 3:
            typhoon_id = str(item[0])
            english = None if item[1] in (None, "") else str(item[1])
            name = str(item[2] or typhoon_id)
            start = _text_time(item[6] if len(item) > 6 else None)
        else:
            continue
        if not typhoon_id:
            continue
        out.append(
            {
                "typhoon_id": typhoon_id,
                "name": name,
                "english_name": english,
                "start_time": start or datetime.utcnow().replace(minute=0, second=0, microsecond=0),
            }
        )
    return out


def parse_warnings(text: str, typhoon_id: str) -> list[dict[str, Any]]:
    data = unwrap_jsonp(text)
    rows = []
    if isinstance(data, dict):
        rows = data.get("warnings") or data.get("warn") or data.get("w") or []
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        warning_id = str(item.get("id") or item.get("warning_id") or "")
        if not warning_id:
            continue
        out.append(
            {
                "warning_id": warning_id,
                "typhoon_id": typhoon_id,
                "level": item.get("level"),
                "title": item.get("title"),
                "issued_at": _text_time(item.get("issued_at") or item.get("time")),
                "areas": item.get("areas") or item.get("provinces") or [],
                "status": item.get("status") or "active",
            }
        )
    return out


def fetch_text(url: str, timeout: int = 15) -> str:
    with urlopen(url, timeout=timeout) as response:  # noqa: S310 - public typhoon bulletin
        return response.read().decode("utf-8", errors="replace")


def _snapshot(db: Session, dataset_id: str, event_id: int | None, url: str, body: str, published_at: datetime | None) -> None:
    db.add(
        SourceSnapshot(
            dataset_id=dataset_id,
            event_id=event_id,
            source_type="cma",
            url=url,
            published_at=published_at,
            fetched_at=datetime.utcnow(),
            content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            body=body[:20000],
        )
    )


def sync_cma_events(
    db: Session,
    dataset_id: str,
    *,
    list_text: str | None = None,
    warning_texts: dict[str, str] | None = None,
    fetcher: Callable[[str], str] | None = None,
) -> dict[str, Any]:
    """Create or merge events by typhoon id and append warnings by warning id."""
    fetch = fetcher or fetch_text
    bulletin = list_text if list_text is not None else fetch(LIST_URL)
    typhoons = parse_typhoon_list(bulletin)
    _snapshot(db, dataset_id, None, LIST_URL, bulletin, None)
    created = merged = warnings = 0
    for item in typhoons:
        event, was_merged = register_or_merge(
            db,
            {
                "dataset_id": dataset_id,
                "event_code": item["typhoon_id"],
                "name": item["name"],
                "english_name": item["english_name"],
                "external_typhoon_id": item["typhoon_id"],
                "start_time": item["start_time"],
                "end_time": None,
                "status": "tracking",
                "source_mode": "auto",
                "warning_level": None,
                "forecast_provinces": None,
                "aliases": None,
            },
        )
        created += 0 if was_merged else 1
        merged += 1 if was_merged else 0
        if warning_texts is not None and item["typhoon_id"] not in warning_texts:
            continue
        view_url = VIEW_URL.format(typhoon_id=item["typhoon_id"])
        view = warning_texts.get(item["typhoon_id"]) if warning_texts is not None else fetch(view_url)
        if not view:
            continue
        _snapshot(db, dataset_id, event.id, view_url, view, None)
        for warn in parse_warnings(view, item["typhoon_id"]):
            row = (
                db.query(WarningRecord)
                .filter(WarningRecord.dataset_id == dataset_id, WarningRecord.warning_id == warn["warning_id"])
                .first()
            )
            if row is None:
                row = WarningRecord(dataset_id=dataset_id, event_id=event.id, warning_id=warn["warning_id"])
                db.add(row)
                warnings += 1
            row.level = warn["level"]
            row.title = warn["title"]
            row.issued_at = warn["issued_at"]
            row.arrived_at = datetime.utcnow()
            row.areas = warn["areas"]
            row.status = warn["status"]
            if warn["level"]:
                event.warning_level = str(warn["level"])
            if isinstance(warn["areas"], list) and warn["areas"]:
                event.forecast_provinces = warn["areas"]
    db.commit()
    return {"typhoons": len(typhoons), "created": created, "merged": merged, "warnings": warnings}
