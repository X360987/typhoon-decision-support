"""从中央气象台公开年度目录导出本地 CSV，不连接数据库、不执行 JSONP。"""

import argparse
import csv
import hashlib
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

BASE = "https://typhoon.nmc.cn"
FIELDS = ["id", "name", "source_url"]
DETAIL_FIELDS = FIELDS + [
    "year",
    "name_en",
    "nmc_record_id",
    "international_code",
    "status",
    "list_url",
]


def parse_catalog(payload: bytes, year: int):
    """严格解析年度 JSONP，只收录该年份具有官方编号与名称的记录。"""
    text = payload.decode("utf-8-sig").strip()
    match = re.fullmatch(rf"typhoon_jsons_list_{year}\s*\((.*)\)\s*;?", text, re.DOTALL)
    if not match:
        raise ValueError(f"{year} 年响应不是预期的官方目录 JSONP")
    document = json.loads(match.group(1))
    rows = document.get("typhoonList")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{year} 年目录为空或结构变化，不生成不完整目录")
    accepted, excluded, seen = [], [], set()
    for row in rows:
        if not isinstance(row, list) or len(row) < 8:
            raise ValueError(f"{year} 年目录字段结构发生变化")
        # 字段对应官网脚本 item[0] 站内 ID、[1] 英文名、[2] 中文名、[4] 展示编号。
        code = str(row[4] or "").strip()
        if not code:
            excluded.append(
                {"year": year, "reason": "无官方展示编号，不作为编号台风导入", "raw": row}
            )
            continue
        if not re.fullmatch(r"\d{4}", code) or code[:2] != str(year)[2:] or code.endswith("00"):
            raise ValueError(f"{year} 年目录编号异常：{code!r}")
        if code in seen:
            raise ValueError(f"{year} 年存在重复官方编号：{code}")
        if not isinstance(row[0], int) or row[0] <= 0:
            raise ValueError("站内记录 ID 格式变化")
        name = str(row[2] or "").strip()
        if not name:
            raise ValueError(f"已编号台风 {code} 缺少中文名，需要复核")
        seen.add(code)
        accepted.append(
            {
                "id": code,
                "name": name,
                "source_url": f"{BASE}/web.html?tid={row[0]}",
                "year": year,
                "name_en": row[1],
                "nmc_record_id": row[0],
                "international_code": row[3],
                "status": row[7],
                "list_url": f"{BASE}/weatherservice/typhoon/jsons/list_{year}",
            }
        )
    if not accepted:
        raise ValueError(f"{year} 年无可导入的编号台风")
    return sorted(accepted, key=lambda row: row["id"]), excluded


def fetch_year(year: int):
    """下载公开响应并验证重定向后的域名；失败重试两次，不绕过访问限制。"""
    from urllib.parse import urlparse

    url = f"{BASE}/weatherservice/typhoon/jsons/list_{year}"
    request = Request(
        url, headers={"User-Agent": "TyphoonResearchCatalog/1.0", "Referer": f"{BASE}/web.html"}
    )
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                if urlparse(response.url).hostname != "typhoon.nmc.cn":
                    raise ValueError("响应重定向至非预期域名")
                payload = response.read(2_000_001)
                if len(payload) > 2_000_000:
                    raise ValueError("年度目录响应超出大小限制")
                return payload, {
                    "year": year,
                    "url": url,
                    "resolved_url": response.url,
                    "retrieved_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("下载未完成")


def write_csv(path: Path, rows: list, fields: list):
    """UTF-8 BOM 方便本地 Excel 查看；ID 仍应按文本列导入。"""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main():
    """默认下载与现有铁路目录一致的 2018—2024 年，拒绝覆盖已有导出目录。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2018)
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument("--output", type=Path, required=True, help="不存在或为空的输出目录")
    args = parser.parse_args()
    if not 2000 <= args.start_year <= args.end_year <= datetime.now(UTC).year:
        parser.error("年份应满足 2000 <= start <= end <= 当前年")
    if args.output.exists() and any(args.output.iterdir()):
        parser.error("输出目录非空；请使用新目录保存新快照")
    # 所有年份下载并验证成功后再落盘，避免把缺年度的结果误当完整目录。
    records, excluded, snapshots = [], [], []
    for year in range(args.start_year, args.end_year + 1):
        payload, provenance = fetch_year(year)
        rows, skipped = parse_catalog(payload, year)
        provenance.update(included=len(rows), excluded=len(skipped))
        records.extend(rows)
        excluded.extend(skipped)
        snapshots.append((year, payload, provenance))
        print(f"{year}: 编号台风 {len(rows)} 条，未编号排除 {len(skipped)} 条", flush=True)
        time.sleep(0.5)
    if len({row["id"] for row in records}) != len(records):
        raise ValueError("跨年度编号重复，需要人工核查")
    args.output.mkdir(parents=True, exist_ok=True)
    raw_dir = args.output / "raw"
    raw_dir.mkdir(exist_ok=True)
    for year, payload, _ in snapshots:
        (raw_dir / f"list_{year}.jsonp").write_bytes(payload)
    write_csv(args.output / "official_typhoons.csv", records, FIELDS)
    write_csv(args.output / "official_typhoons_details.csv", records, DETAIL_FIELDS)
    report = {
        "source": "中央气象台台风网",
        "source_home": f"{BASE}/web.html",
        "field_reference": f"{BASE}/js/typhoon/typhoon-web.js?v=20250924",
        "scope": "官方编号台风目录，不包含路径观测或预报点",
        "years": [args.start_year, args.end_year],
        "total": len(records),
        "number_rule": "官网展示的四位编号 YYNN，不能使用站内记录 ID 代替",
        "annual_sources": [item[2] for item in snapshots],
        "excluded_records": excluded,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"完成：{len(records)} 条；输出 {args.output.resolve()}")


if __name__ == "__main__":
    main()
