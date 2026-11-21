"""官方目录字段与 JSONP 安全解析测试，无网络或数据库写入。"""

import json

import pytest

from app.nmc_catalog import parse_catalog


def payload(rows):
    return ("typhoon_jsons_list_2023(" + json.dumps({"typhoonList": rows}) + ")").encode()


def test_official_number_is_not_internal_id():
    rows, excluded = parse_catalog(
        payload(
            [
                [3274500, "DOKSURI", "杜苏芮", "2305", "2305", None, None, "stop"],
                [123, "nameless", None, "2000", "", 2001, None, "stop"],
            ]
        ),
        2023,
    )
    assert rows[0]["id"] == "2305"
    assert rows[0]["nmc_record_id"] == 3274500
    assert rows[0]["source_url"].endswith("?tid=3274500")
    assert len(excluded) == 1


@pytest.mark.parametrize("code", ["2205", "2300", "202305", "evil"])
def test_reject_unexpected_number(code):
    with pytest.raises(ValueError):
        parse_catalog(payload([[123, "DOKSURI", "杜苏芮", code, code, None, None, "stop"]]), 2023)


def test_reject_script_or_wrong_schema():
    for data in [
        b"alert(1)",
        b'typhoon_jsons_list_2023({"typhoonList":[]})',
        b'typhoon_jsons_list_2023({"typhoonList":[[1]]});alert(1)',
    ]:
        with pytest.raises(ValueError):
            parse_catalog(data, 2023)
