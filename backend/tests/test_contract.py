"""前端契约回归：真实空库、官方事件、按日口径与二步导入。"""

import pytest
from sqlalchemy import func, select
from test_imports import commit, rail, seed, upload

from app.models import Weibo


def setup_event(client):
    assert (
        client.post("/api/v1/datasets", json={"id": "research", "name": "研究"}).status_code == 200
    )
    response = client.post(
        "/api/v1/events",
        json={
            "dataset_id": "research",
            "event_code": "TEST",
            "start_time": "2023-07-01T00:00:00",
            "end_time": "2023-08-31T23:59:59",
        },
    )
    assert response.status_code == 200, response.text
    return {"dataset_id": "research", "event_id": response.json()["id"]}


def test_empty_and_auth(client):
    health = client.get("/api/v1/health").json()
    assert health["data_mode"] == "real" and not health["seed_allowed"]
    assert health["time"].endswith("Z")
    assert client.get("/api/v1/datasets").json()["items"] == []
    bad = client.post("/api/v1/datasets", json={"id": "x", "name": "x"}, headers={"X-API-Key": ""})
    assert bad.status_code == 401 and bad.json()["detail"]["error_code"] == "invalid_api_key"
    response = client.options(
        "/api/v1/datasets",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-API-Key,X-Operator",
        },
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_event_and_filters(client):
    q = setup_event(client)
    event = client.get("/api/v1/events", params={"dataset_id": "research"}).json()["items"][0]
    assert type(event["id"]) is int and event["end_time"] == "2023-08-31T23:59:59"
    assert (
        client.post(
            "/api/v1/events",
            json={
                "dataset_id": "research",
                "event_code": "FAKE",
                "start_time": event["start_time"],
                "end_time": event["end_time"],
            },
        ).status_code
        == 422
    )
    for extra in [
        {"province_code": "350000"},
        {"replay_mode": "as_known"},
        {"data_version": "old"},
        {"dataset_id": "other"},
        {"start": "2024-01-01", "end": "2023-01-01"},
    ]:
        assert client.get("/api/v1/impact", params={**q, **extra}).status_code in (404, 422)
    a = client.get("/api/v1/anomalies", params={**q, "analysis_scope": "pair,joint"}).json()
    assert (
        a["status"] == "not_integrated"
        and a["counts"]["pair"] == 0
        and a["context"]["event_id"] == q["event_id"]
    )


def test_daily_metrics_map_export(client):
    q = setup_event(client)
    seed(client)
    commit(client, upload(client, "rail", [rail("G2690/87")], typhoon_id="TEST"))
    result = client.get("/api/v1/metrics/series", params=q).json()
    assert result["granularity"] == "day"
    values = {r["metric_id"]: r["value"] for r in result["items"]}
    assert values["suspension_count"] == 2
    assert "official_weibo_count" not in values
    data = client.get("/api/v1/impact", params=q).json()
    assert data["total"] == 2 and data["unlocated"] == 2 and data["lines"] == []
    out = client.get("/api/v1/export/metrics", params=q, headers={"X-API-Key": ""})
    assert out.status_code == 200 and "date_bj" in out.text


@pytest.mark.parametrize("policy", ["strict", "skip_errors"])
def test_two_step_and_reuse(client, db, policy):
    q = setup_event(client)
    content = "id,user_id,微博正文,发布时间\n901,902,公告,2023-07-28 12:00:00\n903,902,错误,wrong\n".encode()
    file = {"file": ("posts.csv", content, "text/csv")}
    p = client.post("/api/v1/import/precheck", data={**q, "entity": "weibo"}, files=file)
    assert p.status_code == 200, p.text
    token = p.json()["precheck_token"]
    assert p.json()["blocking_errors"] == 1
    data = {**q, "precheck_token": token, "error_policy": policy, "confirm_skip": "true"}
    bad = client.post(
        "/api/v1/import/commit", data=data, files={"file": ("posts.csv", b"changed", "text/csv")}
    )
    assert bad.status_code == 422 and bad.json()["detail"]["error_code"] == "file_changed"
    result = client.post("/api/v1/import/commit", data=data, files=file)
    if policy == "strict":
        assert result.status_code == 422
        assert db.scalar(select(func.count()).select_from(Weibo)) == 0
        return
    assert result.status_code == 200, result.text
    assert result.json()["inserted"] == 1
    second = client.post(
        "/api/v1/import/precheck", data={**q, "entity": "weibo"}, files=file
    ).json()
    repeated = client.post(
        "/api/v1/import/commit",
        data={**data, "precheck_token": second["precheck_token"]},
        files=file,
    )
    assert repeated.json()["import_status"] == "idempotent_reuse"
    assert db.scalar(select(func.count()).select_from(Weibo)) == 1
    assert type(result.json()["batch_id"]) is int
    batches = client.get("/api/v1/import/batches", params={"dataset_id": "research"}).json()[
        "items"
    ]
    assert batches[0]["created_at"].endswith("Z")


def test_manual_workbook(client, db):
    from io import BytesIO

    from openpyxl import Workbook

    from app.models import ManualSuspension

    q = setup_event(client)
    seed(client)
    commit(client, upload(client, "rail", [rail("G2690")], typhoon_id="TEST"))
    book = Workbook()
    book.active.title = "未匹配车次"
    book.active.append(["日期", "车次"])
    book.active.append(["2023-10-01", "忽略"])
    sheet = book.create_sheet("ID_type长表")
    sheet.append(["日期", "车次", "ID", "type"])
    sheet.append(["2023-09-01", "D2387/6", 2, 3])
    sheet.append(["2023-09-01", "D2387/6", 3, 3])
    data = BytesIO()
    book.save(data)
    files = {"file": ("workbook.xlsx", data.getvalue())}
    for expected in ("imported", "idempotent_reuse"):
        preview = client.post(
            "/api/v1/import/precheck", data={**q, "entity": "rail_manual"}, files=files
        ).json()
        assert preview["rows"] == 2
        if expected == "imported":
            assert preview["duplicates"] == 1
            assert db.scalar(select(func.count()).select_from(ManualSuspension)) == 0
        result = client.post(
            "/api/v1/import/commit",
            files=files,
            data={**q, "precheck_token": preview["precheck_token"], "error_policy": "strict"},
        ).json()
        assert result["import_status"] == expected
        impact = client.get("/api/v1/impact", params=q).json()
        assert impact["daily"] == [{"date": "2023-09-01", "count": 1}]
        assert impact["suspensions"][0]["train_code"] == "D2387/6"
