"""补充接口边界、原模板读取及方向性地图验证。"""

import io

from openpyxl import Workbook
from sqlalchemy import select
from test_imports import commit, rail, seed, upload

from app.imports import read_rows
from app.models import Account, Suspension


def test_xlsx_year_and_text_ids():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "2023"
    sheet.append(["车次", "ID", "type"])
    sheet.append(["G1", "1234567890123456789", 1])
    data = io.BytesIO()
    workbook.save(data)
    rows = read_rows(data.getvalue(), ".xlsx", 100)
    assert rows[0]["ID"] == "1234567890123456789"
    assert rows[0]["_sheet"] == "2023"


def test_declined_identity_change(client, db):
    seed(client)
    p = upload(
        client,
        "weibo",
        [
            {
                "id": "101",
                "user_id": "200",
                "微博正文": "后续",
                "发布时间": "2023-07-29 12:00:00",
                "认证类型": "1",
                "是否权威": "否",
            }
        ],
        typhoon_id="TEST",
    )
    commit(client, p)
    assert db.get(Account, "200").verified_type == "3"
    assert db.get(Account, "200").is_authoritative is True


def test_other_source_keeps_first(client, db):
    seed(client)
    commit(
        client,
        upload(
            client,
            "weibo",
            [
                {
                    "id": "101",
                    "user_id": "201",
                    "微博正文": "另一公告",
                    "发布时间": "2023-07-29 12:00:00",
                }
            ],
            typhoon_id="TEST",
        ),
    )
    a, b = rail(), rail()
    b["公告微博ID"] = "101"
    report = commit(client, upload(client, "rail", [a, b], typhoon_id="TEST"))
    assert report["duplicates"] == 1
    assert db.scalar(select(Suspension)).source_weibo_id == "100"


def test_map_direction(client, db):
    seed(client)
    commit(
        client,
        upload(
            client,
            "stations",
            [
                {"站名": "甲", "经度": "120", "纬度": "30", "坐标系": "WGS84"},
                {"站名": "乙", "经度": "121", "纬度": "31", "坐标系": "WGS84"},
            ],
        ),
    )
    a, b = rail(), rail("G2687")
    b["始发站"], b["终到站"] = "乙", "甲"
    commit(client, upload(client, "rail", [a, b], typhoon_id="TEST"))
    data = client.get("/api/v1/typhoons/TEST/rail/map").json()
    assert data["locatable"] == 2
    assert len(data["lines"]) == 2


def test_invalid_row_partial_and_report(client, db):
    seed(client)
    a, b = rail(), rail("G2687")
    b["停运日期"] = "not-a-date"
    p = upload(client, "rail", [a, b], typhoon_id="TEST")
    result = commit(client, p)
    assert result["inserted"] == 1 and result["error_count"] == 1
    download = client.get(f"/api/v1/imports/{p['batch_id']}/errors")
    assert download.status_code == 200 and "原因" in download.content.decode("utf-8-sig")


def test_invalid_long_id_skips_only_bad_row(client, db):
    good = {"id": "100", "user_id": "200", "微博正文": "正常", "发布时间": "2023-07-29 12:00:00"}
    bad = {**good, "id": "1" * 100}
    result = commit(client, upload(client, "weibo", [bad, good], typhoon_id="TEST"))
    assert result["inserted"] == 1 and result["error_count"] == 1
