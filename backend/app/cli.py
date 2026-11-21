"""离线导入经人工核对的官方台风目录，不提供随意创建事件的网页接口。"""

import argparse
import csv
from urllib.parse import urlparse

from app.db import SessionLocal
from app.models import Typhoon


def main():
    """目录文件须包含 id、name、source_url；来源限官方域名。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("catalog", help="已核对的官方台风目录 UTF-8 CSV")
    args = parser.parse_args()
    with open(args.catalog, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with SessionLocal.begin() as db:
        for row in rows:
            host = (urlparse(row["source_url"]).hostname or "").lower()
            if not any(host == h or host.endswith("." + h) for h in ("nmc.cn", "cma.gov.cn")):
                raise ValueError("目录来源必须为中央气象台或中国气象局官方域名")
            old = db.get(Typhoon, row["id"])
            if old and (old.name != row["name"] or old.source_url != row["source_url"]):
                raise ValueError("已存在官方目录条目冲突，不自动覆盖")
            if not old:
                db.add(Typhoon(id=row["id"], name=row["name"], source_url=row["source_url"]))
    print(f"已核对并处理 {len(rows)} 条目录记录；文件真实性需由数据负责人确认。")


if __name__ == "__main__":
    main()
