"""FastAPI TestClient integration tests on a temporary SQLite database (prompt §5, cases 3, 7, 8, 9, 10, 11, 12)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from app.models import (
    ActiveVersion,
    AnalysisRun,
    Anomaly,
    Dataset,
    Event,
    ProvinceHourMetric,
    ReviewRecord,
    SuspensionRegionHour,
    WeiboClean,
    WeiboRegion,
)
from app.services.pipeline import get_active_version, run_event_pipeline

API = "/api/v1"
TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "templates" / "weibo_template.csv"


def _first_event(client) -> dict:
    items = client.get(f"{API}/events", params={"dataset_id": "demo"}).json()["items"]
    return next(e for e in items if e["event_code"] == "SIM-DOKSURI-2023")


def _csv_rows(text: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))


def _new_event(client, start="2023-07-25T00:00:00", end="2023-07-28T00:00:00") -> int:
    code = f"IT-{uuid.uuid4().hex[:8]}"
    r = client.post(
        f"{API}/events",
        json={"dataset_id": "demo", "event_code": code, "name": code, "start_time": start, "end_time": end},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _precheck(client, data: bytes, event_id: int, name="weibo.csv", **form):
    return client.post(
        f"{API}/import/precheck",
        files={"file": (name, data, "text/csv")},
        data={"entity": "weibo", "dataset_id": "demo", "event_id": str(event_id), **form},
    )


def _commit(client, data: bytes, event_id: int, token: str, name="weibo.csv", **form):
    return client.post(
        f"{API}/import/commit",
        files={"file": (name, data, "text/csv")},
        data={"dataset_id": "demo", "event_id": str(event_id), "precheck_token": token, **form},
    )


# Mode isolation, write permission, review ownership (cases 10, 12) -----------


def test_mode_isolation_hides_and_protects_other_mode(client, db):
    if db.get(Dataset, "real-it") is None:
        db.add(Dataset(id="real-it", name="real", data_mode="real", description="it"))
        db.add(
            Event(
                dataset_id="real-it",
                event_code="REAL-1",
                name="real",
                start_time=datetime(2023, 7, 26),
                end_time=datetime(2023, 7, 27),
            )
        )
        db.commit()
    real_event = db.query(Event).filter(Event.dataset_id == "real-it").first()

    ids = [d["id"] for d in client.get(f"{API}/datasets").json()["items"]]
    assert "demo" in ids and "real-it" not in ids
    assert client.get(f"{API}/events", params={"dataset_id": "real-it"}).status_code == 403
    r = client.get(f"{API}/anomalies", params={"dataset_id": "real-it", "event_id": real_event.id})
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "mode_mismatch"
    r = client.post(f"{API}/pipeline/rerun", params={"dataset_id": "real-it", "event_id": real_event.id})
    assert r.status_code == 403


def test_real_mode_never_seeds_or_falls_back_to_demo(client, settings_env):
    settings_env(data_mode="real")
    health = client.get(f"{API}/health").json()
    assert health["seed_allowed"] is False and health["write_requires_key"] is True
    r = client.post(f"{API}/admin/seed")
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "write_disabled"
    assert all(d["data_mode"] == "real" for d in client.get(f"{API}/datasets").json()["items"])
    assert client.get(f"{API}/events", params={"dataset_id": "demo"}).status_code == 403

    settings_env(data_mode="real", api_key="k-real")
    r = client.post(f"{API}/admin/seed", headers={"X-API-Key": "k-real"})
    assert r.status_code == 403 and r.json()["detail"]["error_code"] == "seed_forbidden"


def test_writes_require_api_key_and_record_operator(client, settings_env):
    ev = _first_event(client)
    anomaly = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"], "page_size": 1}).json()["items"][0]
    body = {"dataset_id": "demo", "target_type": "anomaly", "target_id": anomaly["id"], "action": "need_evidence", "note": "补原文"}

    settings_env(api_key="s3cret")
    assert client.post(f"{API}/review", json=body).status_code == 401
    assert client.post(f"{API}/review", json=body, headers={"X-API-Key": "wrong"}).status_code == 401
    for path, kwargs in (
        ("/admin/seed", {}),
        ("/pipeline/rerun", {"params": {"dataset_id": "demo", "event_id": ev["id"]}}),
        ("/predictions/run", {"json": {"dataset_id": "demo", "event_id": ev["id"], "origin_time": ev["start_time"]}}),
        ("/events", {"json": {"dataset_id": "demo", "event_code": "X", "name": "X", "start_time": ev["start_time"], "end_time": ev["end_time"]}}),
    ):
        assert client.post(f"{API}{path}", **kwargs).status_code == 401, path

    r = client.post(f"{API}/review", json=body, headers={"X-API-Key": "s3cret", "X-Operator": "alice"})
    assert r.status_code == 200 and r.json()["operator"] == "alice"
    hist = client.get(
        f"{API}/reviews", params={"dataset_id": "demo", "target_type": "anomaly", "target_id": anomaly["id"]}
    ).json()["items"]
    assert hist[0]["operator"] == "alice" and hist[0]["action"] == "need_evidence" and hist[0]["created_at"]


def test_review_rejects_bad_action_and_cross_dataset_target(client, db):
    if db.get(Dataset, "demo-other") is None:
        db.add(Dataset(id="demo-other", name="other", data_mode="demo", description="it"))
        db.commit()
    ev = _first_event(client)
    anomaly = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"], "page_size": 1}).json()["items"][0]
    base = {"dataset_id": "demo", "target_type": "anomaly", "target_id": anomaly["id"], "action": "approve"}

    assert client.post(f"{API}/review", json={**base, "action": "publish"}).status_code == 400
    assert client.post(f"{API}/review", json={**base, "target_type": "event"}).status_code == 400
    assert client.post(f"{API}/review", json={**base, "target_id": 10_000_000}).status_code == 404
    r = client.post(f"{API}/review", json={**base, "dataset_id": "demo-other"})
    assert r.status_code == 404 and r.json()["detail"]["error_code"] == "target_not_found"
    assert db.query(ReviewRecord).filter(ReviewRecord.dataset_id == "demo-other").count() == 0


# Import (case 8) -------------------------------------------------------------


def test_import_precheck_commit_and_idempotent_retry(client):
    event_id = _new_event(client)
    data = TEMPLATE.read_bytes()
    pre = _precheck(client, data, event_id)
    assert pre.status_code == 200, pre.text
    report = pre.json()
    assert report["ok"] is True and report["precheck_token"] and report["allowed_policies"] == ["strict"]

    first = _commit(client, data, event_id, report["precheck_token"])
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["import_status"] == "imported" and body["inserted"] == 2
    assert body["analysis_status"] == "success"

    again = _commit(client, data, event_id, report["precheck_token"])
    assert again.status_code == 200 and again.json()["import_status"] == "idempotent_reuse"
    batches = client.get(f"{API}/import/batches", params={"dataset_id": "demo"}).json()["items"]
    assert any(b["id"] == body["batch_id"] and b["analysis_status"] == "success" for b in batches)


def test_import_rejects_forged_or_mismatched_token(client):
    event_id = _new_event(client)
    data = TEMPLATE.read_bytes()
    token = _precheck(client, data, event_id).json()["precheck_token"]

    body, sig = token.rsplit(".", 1)
    forged = body + "." + ("0" if sig[0] != "0" else "1") + sig[1:]
    r = _commit(client, data, event_id, forged)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "invalid_token"
    assert _commit(client, data, event_id, "not-a-token").json()["detail"]["error_code"] == "invalid_token"

    changed = data.replace(b"REAL-WB-002", b"REAL-WB-099")
    r = _commit(client, changed, event_id, token)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "token_mismatch"

    other_event = _new_event(client)
    r = _commit(client, data, other_event, token)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "token_mismatch"

    r = _commit(client, data, event_id, token, column_mapping='{"text":"content"}')
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "token_mismatch"


def test_import_bad_rows_need_explicit_skip_and_record_errors(client):
    event_id = _new_event(client)
    data = (
        "source_id,user_id,content,published_at,available_at,likes,publish_location\n"
        "IT-OK-1,U1,福建台风停运,2023-07-26 10:00:00,2023-07-26 10:05:00,3,福建\n"
        "IT-BAD-2,U2,广东暴雨,not-a-time,,4,广东\n"
        "IT-BAD-3,U3,浙江大风,2023-07-26 11:00:00,2023-07-26 11:02:00,-5,浙江\n"
        "IT-OK-1,U1,重复行,2023-07-26 10:00:00,2023-07-26 10:05:00,3,福建\n"
    ).encode("utf-8")
    report = _precheck(client, data, event_id).json()
    assert report["ok"] is False and report["blocking_errors"] == 2 and report["duplicates"] == 1
    assert report["allowed_policies"] == ["skip_errors"]
    token = report["precheck_token"]

    r = _commit(client, data, event_id, token)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "row_errors"
    r = _commit(client, data, event_id, token, error_policy="skip_errors")
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "confirm_required"
    r = _commit(client, data, event_id, token, error_policy="skip_errors", confirm_skip="true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["inserted"] == 1 and body["skipped"] == 1
    errors = client.get(f"{API}/import/errors/{body['batch_id']}", params={"dataset_id": "demo"}).json()["items"]
    assert sorted(e["row_number"] for e in errors) == [3, 4]


def test_import_rejects_format_size_and_missing_columns(client, settings_env):
    event_id = _new_event(client)
    r = _precheck(client, b"a,b\n1,2\n", event_id, name="weibo.txt")
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "bad_format"
    r = _precheck(client, b"", event_id)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "empty_file"

    missing = _precheck(client, b"source_id,content\n1,x\n", event_id).json()
    assert missing["error"] == "missing_columns" and missing["precheck_token"] is None

    settings_env(max_upload_mb=0)
    r = _precheck(client, TEMPLATE.read_bytes(), event_id)
    assert r.status_code == 400 and r.json()["detail"]["error_code"] == "file_too_large"


# Rerun atomicity and traceability (cases 8, 9) -------------------------------


def test_failed_rerun_keeps_previous_version_serving(client, db):
    ev = _first_event(client)
    before = get_active_version(db, "demo", ev["id"])
    listed_before = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"]}).json()

    result = run_event_pipeline(db, "demo", ev["id"], trigger="it", fail_at="anomalies")
    assert result["ok"] is False and result["active_version"] == before
    failed = db.get(AnalysisRun, result["run_id"])
    assert failed.status == "failed" and failed.data_version is None
    half_version = f"r{result['run_id']}"
    assert db.query(ProvinceHourMetric).filter(ProvinceHourMetric.version == half_version).count() == 0

    listed_after = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"]}).json()
    assert listed_after["context"]["data_version"] == before
    assert listed_after["total"] == listed_before["total"]


def test_successful_rerun_switches_and_old_version_stays_queryable(client, db):
    ev = _first_event(client)
    old = get_active_version(db, "demo", ev["id"])
    anomaly = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"], "page_size": 1}).json()["items"][0]
    client.post(
        f"{API}/review",
        json={"dataset_id": "demo", "target_type": "anomaly", "target_id": anomaly["id"], "action": "approve"},
    )

    r = client.post(f"{API}/pipeline/rerun", params={"dataset_id": "demo", "event_id": ev["id"]})
    assert r.status_code == 200 and r.json()["status"] == "success"
    db.expire_all()
    new = get_active_version(db, "demo", ev["id"])
    assert new != old

    runs = client.get(f"{API}/analysis/runs", params={"dataset_id": "demo", "event_id": ev["id"]}).json()["items"]
    assert any(x["data_version"] == new and x["active"] for x in runs)
    old_list = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"], "data_version": old}).json()
    assert old_list["total"] > 0 and old_list["context"]["data_version"] == old
    detail = client.get(f"{API}/anomalies/{anomaly['id']}", params={"dataset_id": "demo"}).json()
    assert detail["anomaly"]["data_version"] == old and detail["reviews"]


# Pagination, export consistency, as_known (cases 3, 11) ----------------------


def test_pagination_reaches_past_first_hundred_and_export_matches(client, db):
    event_id = _new_event(client, "2023-08-01T00:00:00", "2023-08-10T00:00:00")
    version = get_active_version(db, "demo", event_id)
    start = datetime(2023, 8, 1)
    for i in range(130):
        hour = start + timedelta(hours=i)
        db.add(
            Anomaly(
                dataset_id="demo",
                event_id=event_id,
                analysis_scope="single",
                dimensions=["social"],
                dims_key=",social,",
                anomaly_type="discussion_spike",
                province_code="FJ" if i % 2 else "GD",
                hour_bj=hour,
                available_at=hour + timedelta(hours=1),
                rule_version="it",
                data_version=version,
                group_key=f"it:{event_id}:{i}",
                explanation="it",
            )
        )
    db.commit()

    seen: list[int] = []
    page = 1
    while True:
        body = client.get(
            f"{API}/anomalies", params={"dataset_id": "demo", "event_id": event_id, "page": page, "page_size": 50}
        ).json()
        assert body["total"] == 130
        if not body["items"]:
            break
        seen += [a["id"] for a in body["items"]]
        page += 1
    assert len(seen) == len(set(seen)) == 130

    rows = _csv_rows(client.get(f"{API}/export/anomalies", params={"dataset_id": "demo", "event_id": event_id}).text)
    assert [int(r["anomaly_id"]) for r in rows] == seen
    assert {r["data_mode"] for r in rows} == {"demo"} and {r["data_version"] for r in rows} == {version}

    filt = {"dataset_id": "demo", "event_id": event_id, "province_code": "FJ", "page_size": 200}
    listed = [a["id"] for a in client.get(f"{API}/anomalies", params=filt).json()["items"]]
    filtered_rows = _csv_rows(client.get(f"{API}/export/anomalies", params=filt).text)
    exported = [int(r["anomaly_id"]) for r in filtered_rows]
    assert listed == exported and len(listed) == 65
    assert "省份=FJ" in filtered_rows[0]["filter_summary"]
    assert filtered_rows[0]["timezone"] and filtered_rows[0]["evidence_ids"] is not None


def test_as_known_hides_later_arrivals_and_retrospective_shows_them(client, db):
    event_id = _new_event(client, "2023-09-01T00:00:00", "2023-09-03T00:00:00")
    version = get_active_version(db, "demo", event_id)
    hour = datetime(2023, 9, 1, 10)
    late = Anomaly(
        dataset_id="demo",
        event_id=event_id,
        analysis_scope="pair",
        dimensions=["organizational", "physical"],
        dims_key=",organizational,physical,",
        anomaly_type="org_physical_response_lag",
        province_code="ZJ",
        hour_bj=hour,
        available_at=hour + timedelta(hours=5),
        requires_future_window=True,
        rule_version="it",
        data_version=version,
        group_key=f"it-late:{event_id}",
        explanation="it",
    )
    db.add(late)
    db.commit()
    params = {"dataset_id": "demo", "event_id": event_id}

    as_of = (hour + timedelta(hours=2)).isoformat()
    strict = client.get(f"{API}/anomalies", params={**params, "replay_mode": "as_known", "as_of": as_of}).json()
    assert strict["total"] == 0 and strict["pending_window"] == 1
    later = client.get(
        f"{API}/anomalies", params={**params, "replay_mode": "as_known", "as_of": (hour + timedelta(hours=6)).isoformat()}
    ).json()
    assert later["total"] == 1
    retro = client.get(f"{API}/anomalies", params={**params, "replay_mode": "retrospective"}).json()
    assert retro["total"] == 1 and retro["context"]["replay_mode"] == "retrospective"

    detail = client.get(
        f"{API}/anomalies/{late.id}", params={"dataset_id": "demo", "replay_mode": "as_known", "as_of": as_of}
    ).json()
    assert detail["visible_at_as_of"] is False

    relation = client.get(f"{API}/anomalies", params={**params, "analysis_scope": "pair,joint"}).json()
    assert relation["total"] == 1
    assert client.get(f"{API}/anomalies", params={**params, "analysis_scope": "single"}).json()["total"] == 0
    assert client.get(f"{API}/anomalies", params={**params, "analysis_scope": "pair,bogus"}).status_code == 400


def test_timeline_window_and_as_known_cut(client):
    ev = _first_event(client)
    params = {"dataset_id": "demo", "event_id": ev["id"], "limit": 500}
    cursor = datetime(2023, 7, 27, 12)
    window = {"known_from": (cursor - timedelta(hours=12)).isoformat(), "known_to": (cursor + timedelta(hours=6)).isoformat()}
    retro = client.get(f"{API}/timeline", params={**params, **window}).json()["items"]
    assert retro, "window should contain records"
    for it in retro:
        assert window["known_from"] <= it["known_at"] <= window["known_to"]
    assert any(it["known_at"] > cursor.isoformat() for it in retro)

    strict = client.get(
        f"{API}/timeline",
        params={**params, "known_from": window["known_from"], "replay_mode": "as_known", "as_of": cursor.isoformat()},
    ).json()["items"]
    assert strict and all(it["known_at"] <= cursor.isoformat() for it in strict)
    before = {it["ref"] for it in retro if it["known_at"] <= cursor.isoformat()}
    assert {it["ref"] for it in strict} <= before


def test_system_timestamps_are_marked_utc_and_batch_keeps_upload_name(client):
    ev = _first_event(client)
    anomaly_id = client.get(f"{API}/anomalies", params={"dataset_id": "demo", "event_id": ev["id"]}).json()["items"][0]["id"]
    rec = client.post(
        f"{API}/review", json={"dataset_id": "demo", "target_type": "anomaly", "target_id": anomaly_id, "action": "need_evidence"}
    ).json()
    assert rec["created_at"].endswith("Z")
    event_id = _new_event(client)
    data = TEMPLATE.read_bytes()
    token = _precheck(client, data, event_id, name="福建微博.csv").json()["precheck_token"]
    _commit(client, data, event_id, token, name="福建微博.csv")
    batches = client.get(f"{API}/import/batches", params={"dataset_id": "demo"}).json()["items"]
    mine = [b for b in batches if b["event_id"] == event_id]
    assert mine and mine[0]["file_name"] == "福建微博.csv"
    assert mine[0]["created_at"].endswith("Z")


def test_as_known_metrics_respect_available_at(client, db):
    ev = _first_event(client)
    as_of = datetime.fromisoformat(ev["start_time"]) + timedelta(hours=30)
    body = client.get(
        f"{API}/metrics/series",
        params={"dataset_id": "demo", "event_id": ev["id"], "replay_mode": "as_known", "as_of": as_of.isoformat()},
    ).json()
    points = body["items"]
    assert points
    cutoff = as_of.isoformat()
    assert all(p["available_at"] and p["available_at"] <= cutoff for p in points)
    # Social counts close at H+1h; suspension notices are published ahead, so physical rows may surface at H.
    physical = {"affected_trains", "suspension_events", "affected_stations"}
    assert all(p["hour_bj"] < cutoff for p in points if p["metric_id"] not in physical)
    assert all(p["hour_bj"] <= cutoff for p in points)


# Aggregation rules (case 7) ----------------------------------------------------


def test_national_counts_are_deduplicated_and_stations_are_real_sets(db):
    ev = db.query(Event).filter(Event.dataset_id == "demo", Event.event_code == "SIM-DOKSURI-2023").one()
    version = get_active_version(db, "demo", ev.id)

    def metric(prov, hour, mid):
        row = (
            db.query(ProvinceHourMetric)
            .filter(
                ProvinceHourMetric.dataset_id == "demo",
                ProvinceHourMetric.event_id == ev.id,
                ProvinceHourMetric.version == version,
                ProvinceHourMetric.province_code == prov,
                ProvinceHourMetric.hour_bj == hour,
                ProvinceHourMetric.metric_id == mid,
            )
            .first()
        )
        return None if row is None else row.value

    pairs = (
        db.query(WeiboClean.id, WeiboClean.hour_bj, WeiboRegion.province_code)
        .join(WeiboRegion, WeiboRegion.weibo_clean_id == WeiboClean.id)
        .filter(WeiboClean.event_id == ev.id, WeiboClean.account_class == "personal")
        .all()
    )
    by_hour: dict[datetime, set[int]] = {}
    multi: dict[datetime, int] = {}
    for wid, hour, _prov in pairs:
        by_hour.setdefault(hour, set()).add(wid)
        multi[hour] = multi.get(hour, 0) + 1
    hour = max(by_hour, key=lambda h: multi[h] - len(by_hour[h]))
    assert metric("ALL", hour, "personal_weibo_count") == len(by_hour[hour])

    srows = db.query(SuspensionRegionHour).filter(SuspensionRegionHour.event_id == ev.id).all()
    assert srows
    s_hour = srows[0].hour_bj
    same = [r for r in srows if r.hour_bj == s_hour]
    assert metric("ALL", s_hour, "affected_trains") == len({r.run_key for r in same})
    assert metric("ALL", s_hour, "affected_stations") == len({s for r in same for s in (r.stations or [])})


# Prediction honesty (case 5) ---------------------------------------------------


def test_predictions_mark_ml_only_on_h3_and_never_fake_intervals(client):
    ev = _first_event(client)
    body = client.get(f"{API}/predictions", params={"dataset_id": "demo", "event_id": ev["id"]}).json()
    assert body["run"] is not None and body["items"]
    origin = datetime.fromisoformat(body["run"]["origin_time"])
    for item in body["items"]:
        assert item["interval_low"] is None and item["interval_reason"]
        if item["lead_hours"] != body["ml_horizon"]:
            assert "ml" not in item["status"]
        if item["train_cutoff"]:
            assert datetime.fromisoformat(item["train_cutoff"]) <= origin
    assert any("ml" in i["status"] for i in body["items"] if i["lead_hours"] == body["ml_horizon"])

    early = datetime.fromisoformat(ev["start_time"]) + timedelta(hours=6)
    r = client.post(f"{API}/predictions/run", json={"dataset_id": "demo", "event_id": ev["id"], "origin_time": early.isoformat()})
    assert r.status_code == 200, r.text
    early_items = client.get(
        f"{API}/predictions", params={"dataset_id": "demo", "event_id": ev["id"], "origin_time": early.isoformat()}
    ).json()["items"]
    h3 = [i for i in early_items if i["lead_hours"] == 3]
    assert h3 and all("ml" not in i["status"] and "model_trained_after_origin" in (i["reason"] or "") for i in h3)


# Business actions are separate from TaskRun ------------------------------------


def test_actions_require_approved_suggestion_and_receipt(client):
    ev = _first_event(client)
    suggestions = client.get(f"{API}/suggestions", params={"dataset_id": "demo", "event_id": ev["id"]}).json()["items"]
    assert suggestions
    sid = suggestions[0]["id"]
    r = client.post(f"{API}/actions", json={"dataset_id": "demo", "suggestion_id": sid})
    if suggestions[0]["review_status"] != "approve":
        assert r.status_code == 409
        client.post(f"{API}/review", json={"dataset_id": "demo", "target_type": "suggestion", "target_id": sid, "action": "approve"})
        r = client.post(f"{API}/actions", json={"dataset_id": "demo", "suggestion_id": sid, "owner": "值班组"})
    assert r.status_code == 200, r.text
    action = r.json()
    r = client.patch(f"{API}/actions/{action['id']}", json={"dataset_id": "demo", "status": "closed"})
    assert r.status_code == 409
    r = client.patch(f"{API}/actions/{action['id']}", json={"dataset_id": "demo", "status": "closed", "receipt": "已电话确认"})
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_active_version_pointer_is_per_event(db):
    rows = db.query(ActiveVersion).filter(ActiveVersion.dataset_id == "demo").all()
    assert len({(r.dataset_id, r.event_id) for r in rows}) == len(rows)
