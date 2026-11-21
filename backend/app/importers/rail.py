"""公告明细中的全程停运。依赖年度车次目录和已入库的来源微博。"""

from collections import defaultdict
from datetime import date

from sqlalchemy import select

from app.importers.ids import split_train
from app.importers.reader import identifier, value
from app.models import Suspension, Train, Weibo


def _facts(row):
    return {
        "origin": value(row, "始发站", "区段起点", "origin"),
        "destination": value(row, "终到站", "区段终点", "destination"),
        "source_id": value(row, "列车数据库ID", "source_train_id"),
    }


class RailImporter:
    def rail(self):
        groups = defaultdict(list)
        for row in self.batch.rows:
            try:
                raw_day = value(row, "停运日期", "departure_date", required=True)
                day = date.fromisoformat(raw_day[:10])
                raw = value(row, "标准车次", "车次", "train_no", required=True)
                codes = split_train(raw)
                if value(row, "停运范围", "scope", required=True) not in {"全程", "全程停运"}:
                    raise ValueError("第一版仅允许全程停运")
                source = identifier(
                    value(
                        row,
                        "公告微博ID",
                        "公告微博ID/公告链接",
                        "source_weibo_id",
                        required=True,
                    )
                )
                for station in (
                    value(row, "始发站", "区段起点", "origin"),
                    value(row, "终到站", "区段终点", "destination"),
                ):
                    if station is not None and len(station) > 100:
                        raise ValueError("车站名称超过 100 字符")
                for no in codes:
                    groups[(day, no)].append((row, raw, source))
            except (ValueError, TypeError) as exc:
                self.issue(row, str(exc))
        for (day, no), items in groups.items():
            conflicts = {
                field: sorted(
                    {
                        _facts(row)[field]
                        for row, _, _ in items
                        if _facts(row)[field] is not None
                    }
                )
                for field in ("origin", "destination", "source_id")
            }
            conflicts = {k: v for k, v in conflicts.items() if len(v) > 1}
            if conflicts:
                for row, _, _ in items:
                    self.issue(row, "同批同车次日存在冲突，整组未写入", no, conflicts=conflicts)
                continue
            train = self.db.scalar(
                select(Train).where(Train.year == day.year, Train.train_no == no)
            )
            existing = (
                self.db.scalar(
                    select(Suspension).where(
                        Suspension.typhoon_id == self.batch.typhoon_id,
                        Suspension.departure_date == day,
                        Suspension.train_id == train.id,
                    )
                )
                if train
                else None
            )
            for row, raw, source in items:
                facts = _facts(row)
                if not train:
                    self.issue(row, f"{day.year} 年目录无对应车次", no)
                    continue
                if facts["source_id"] is not None and facts["source_id"] != train.source_train_id:
                    self.issue(row, "原列车 ID 与年度目录不一致", no)
                    continue
                if not self.db.get(Weibo, source):
                    self.issue(row, "来源微博未入库，请先导入微博正文", no)
                    continue
                if existing:
                    bad = {
                        k: [getattr(existing, k), facts[k]]
                        for k in ("origin", "destination")
                        if getattr(existing, k) is not None
                        and facts[k] is not None
                        and getattr(existing, k) != facts[k]
                    }
                    if bad:
                        self.issue(row, "与数据库已有停运记录冲突，保留原记录", no, conflicts=bad)
                    else:
                        self.report["duplicates"] += 1
                    continue
                existing = Suspension(
                    typhoon_id=self.batch.typhoon_id,
                    departure_date=day,
                    catalog_year=day.year,
                    train_id=train.id,
                    raw_train_no=raw,
                    origin=facts["origin"],
                    destination=facts["destination"],
                    source_weibo_id=source,
                    batch_id=self.batch.id,
                    source_row=row["_row"],
                    evidence={k: v for k, v in row.items() if not k.startswith("_")},
                )
                self.db.add(existing)
                self.db.flush()
                self.report["inserted"] += 1
