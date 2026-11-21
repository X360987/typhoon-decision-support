"""验证关键研究口径，不用 SQLite 替代 PostgreSQL 约束。"""

import csv
import io

from sqlalchemy import func, select

from app.imports import split_train
from app.models import Account, EventPost, Suspension, Weibo


def upload(client, kind, rows, **kwargs):
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    response = client.post(
        "/api/v1/imports/preview",
        data={"kind": kind, **kwargs},
        files={"file": ("test.csv", text.getvalue().encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def commit(client, preview, decisions=None):
    response = client.post(
        f"/api/v1/imports/{preview['batch_id']}/commit", json={"decisions": decisions or {}}
    )
    assert response.status_code == 200, response.text
    return response.json()


def seed(client):
    commit(
        client,
        upload(
            client,
            "trains",
            [{"车次": "G2690", "ID": "1"}, {"车次": "G2687", "ID": "2"}],
            catalog_year=2023,
        ),
    )
    commit(
        client,
        upload(
            client,
            "weibo",
            [
                {
                    "id": "100",
                    "user_id": "200",
                    "微博正文": "公告",
                    "发布时间": "2023-07-28 12:00:00",
                    "认证类型": "3",
                    "是否权威": "是",
                    "阶段": "灾中",
                }
            ],
            typhoon_id="TEST",
        ),
    )


def rail(no="G2690", **changes):
    return dict(
        标准车次=no,
        停运日期="2023-07-29",
        停运范围="全程停运",
        始发站="甲",
        终到站="乙",
        公告微博ID="100",
        **changes,
    )


def test_slash():
    assert split_train("G2690/87") == ["G2690", "G2687"]


def test_weibo_source_format(client, db):
    row = {"id": "4.92753E+15", "bid": "NbycE8Aj9", "user_id": "200",
           "微博正文": "公告", "发布时间": "2023/7/25 9:05", "阶段": "准备阶段"}
    rows = [row, dict(row, id="102", 阶段="响应阶段"), dict(row, id="103", 阶段="恢复阶段"),
            dict(row, id="104", 微博正文="  "), dict(row, id="1.11111E+15")]
    result = commit(client, upload(client, "weibo", rows, typhoon_id="TEST"))
    assert (result["inserted"], result["error_count"]) == (3, 2)
    assert set(db.scalars(select(EventPost.stage))) == {"灾前", "灾中", "灾后"}
    assert db.get(Weibo, "104") is None


def test_preview_rollback_commit_idempotent(client, db):
    seed(client)
    result = upload(client, "rail", [rail("G2690/87")], typhoon_id="TEST")
    assert result["inserted"] == 2
    assert db.scalar(select(func.count()).select_from(Suspension)) == 0
    first = commit(client, result)
    second = commit(client, result)
    assert first == second
    assert db.scalar(select(func.count()).select_from(Suspension)) == 2


def test_same_batch_conflict_rejects_group(client, db):
    seed(client)
    a, b = rail(), rail()
    b["终到站"] = "丙"
    report = commit(client, upload(client, "rail", [a, b, rail("G2687")], typhoon_id="TEST"))
    assert report["error_count"] == 2
    assert report["inserted"] == 1


def test_existing_conflict_and_duplicate(client, db):
    seed(client)
    commit(client, upload(client, "rail", [rail()], typhoon_id="TEST"))
    a = rail()
    a["终到站"] = "丙"
    report = commit(client, upload(client, "rail", [a], typhoon_id="TEST"))
    assert report["error_count"] == 1
    assert db.scalar(select(Suspension)).destination == "乙"
    assert commit(client, upload(client, "rail", [rail()], typhoon_id="TEST"))["duplicates"] == 1


def test_partial_slash_missing_train(client, db):
    seed(client)
    report = commit(client, upload(client, "rail", [rail("G2690/99")], typhoon_id="TEST"))
    assert report["inserted"] == 1
    assert report["errors"][0]["train_no"] == "G2699"


def test_missing_source_and_year(client, db):
    seed(client)
    a, b = rail(), rail("G2687")
    a["公告微博ID"] = "999"
    b["停运日期"] = "2024-07-29"
    report = commit(client, upload(client, "rail", [a, b], typhoon_id="TEST"))
    assert report["error_count"] == 2
    assert report["inserted"] == 0


def test_duplicates_keep_first_without_fill(client, db):
    seed(client)
    a, b = rail(), rail()
    a["终到站"] = ""
    report = commit(client, upload(client, "rail", [a, b], typhoon_id="TEST"))
    assert report["inserted"] == 1 and report["duplicates"] == 1
    assert db.scalar(select(Suspension)).destination is None


def test_identity_confirmation_snapshot(client, db):
    seed(client)
    row = {
        "id": "101",
        "user_id": "200",
        "微博正文": "后续",
        "发布时间": "2023-07-29 12:00:00",
        "认证类型": "1",
        "是否权威": "否",
    }
    p = upload(client, "weibo", [row], typhoon_id="TEST")
    tokens = {x["decision_token"]: True for x in p["warnings"] if "decision_token" in x}
    commit(client, p, tokens)
    assert db.get(Account, "200").verified_type == "1"
    assert db.get(EventPost, ("TEST", "100")).verified_type == "3"
    assert db.get(EventPost, ("TEST", "100")).is_authoritative is True
    assert db.get(Weibo, "101").likes is None


def test_map_and_china_date(client, db):
    seed(client)
    commit(client, upload(client, "rail", [rail("G2690/87")], typhoon_id="TEST"))
    report = client.get("/api/v1/typhoons/TEST/rail/map").json()
    assert report["total"] == 2 and report["locatable"] == 0
    assert (
        client.get(
            "/api/v1/typhoons/TEST/overview?start_date=2023-07-28&end_date=2023-07-28"
        ).json()["weibo"]["count"]
        == 1
    )
    assert (
        client.get(
            "/api/v1/typhoons/TEST/rail/statistics?start_date=2023-08-01&end_date=2023-07-01"
        ).status_code
        == 422
    )
    assert client.get("/api/v1/typhoons/TEST/social/analysis").json()["status"] == "not_integrated"


def test_unknown_event_rejected(client):
    response = client.get("/api/v1/typhoons/UNKNOWN/overview")
    assert response.status_code == 404
