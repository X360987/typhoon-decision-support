"""Keyword rules, typhoon merge, CMA parsing, coupling and multi-metric trend."""

from datetime import datetime, timedelta

from app.during.coupling import lead_lag
from app.during.multi_trend import synthesize
from app.pre.cma import parse_typhoon_list, parse_warnings, sync_cma_events
from app.pre.events import register_or_merge
from app.pre.keywords import build_keyword_set


def test_keywords_follow_the_confirmed_rule():
    built = build_keyword_set(
        name="杜苏芮",
        english_name="DOKSURI",
        typhoon_id="202305",
        aliases=["苏芮"],
        provinces=["FJ"],
    )
    for word in ("杜苏芮", "DOKSURI", "202305", "苏芮", "台风福建"):
        assert word in built["keywords"]
    assert built["negative_keywords"]
    assert len(built["keywords"]) == len(set(built["keywords"]))


def test_same_typhoon_id_merges(db):
    start = datetime(2024, 7, 1, 0, 0, 0)
    first, merged = register_or_merge(
        db,
        {
            "dataset_id": "demo",
            "event_code": "202401",
            "name": "旧名",
            "external_typhoon_id": "202401",
            "start_time": start,
            "end_time": None,
            "status": "tracking",
            "source_mode": "manual",
            "english_name": None,
            "aliases": None,
            "warning_level": None,
            "forecast_provinces": ["FJ"],
        },
    )
    db.commit()
    assert merged is False
    second, merged = register_or_merge(
        db,
        {
            "dataset_id": "demo",
            "event_code": "manual-1",
            "name": "新名",
            "external_typhoon_id": "202401",
            "start_time": start,
            "end_time": None,
            "status": "tracking",
            "source_mode": "auto",
            "english_name": "TEST",
            "aliases": None,
            "warning_level": "blue",
            "forecast_provinces": ["GD"],
        },
    )
    db.commit()
    assert merged is True and second.id == first.id and second.name == "新名" and second.event_code == "202401"


def test_cma_list_and_warning_sync(db):
    bulletin = 'typhoon_jsons_list_default({"typhoonList":[[202411,"KONG-REY","康芮",202411,202411,null,"2024-10-25 08:00:00"]]})'
    view = '{"warnings":[{"id":"W1","level":"orange","title":"台风橙色预警","issued_at":"2024-10-25T08:00:00","areas":["FJ"]}]}'
    parsed = parse_typhoon_list(bulletin)
    assert parsed[0]["name"] == "康芮" and parsed[0]["typhoon_id"] == "202411"
    assert parse_warnings(view, "202411")[0]["warning_id"] == "W1"
    result = sync_cma_events(db, "demo", list_text=bulletin, warning_texts={"202411": view})
    assert result["created"] == 1 and result["warnings"] == 1
    again = sync_cma_events(db, "demo", list_text=bulletin, warning_texts={"202411": view})
    assert again["created"] == 0 and again["merged"] == 1 and again["warnings"] == 0


def test_lead_lag_finds_delayed_series():
    start = datetime(2024, 1, 1)
    pattern = [0.0, 5.0, 1.0, 4.0, 2.0, 0.2, 3.0, 1.5]
    left = {start + timedelta(hours=i): value for i, value in enumerate(pattern)}
    right = {start + timedelta(hours=i + 2): value for i, value in enumerate(pattern)}
    result = lead_lag(left, right, 6)
    assert result["lead_lag_hours"] == 2
    assert result["state"] == "lag"
    assert result["strength"] > 0.9


def test_multi_trend_has_no_interval():
    items = [
        {"target_id": "negative_ratio", "province_code": "FJ", "lead_hours": 1, "valid_time": "t", "point_pred": 0.4},
        {"target_id": "personal_weibo_count", "province_code": "FJ", "lead_hours": 1, "valid_time": "t", "point_pred": 3},
    ]
    rows = synthesize(items)
    assert rows[0]["sample_size"] == 2
    assert rows[0]["interval_low"] is None and rows[0]["interval_high"] is None
