"""人工长表。只保留日期、车次、批次和原始行号，不在这里补站名。"""

from datetime import datetime, time

from sqlalchemy import select

from app.contract_models import ResearchEvent
from app.importers.reader import value
from app.models import ManualSuspension
from app.timeutil import TZ


class ManualImporter:
    def manual_rail(self):
        event = self.batch.typhoon_id
        seen = set(
            self.db.execute(
                select(ManualSuspension.departure_date, ManualSuspension.raw_train_no).where(
                    ManualSuspension.typhoon_id == event
                )
            )
        )
        for row in self.batch.rows:
            try:
                day = datetime.fromisoformat(value(row, "日期", required=True)).date()
                code = value(row, "车次", required=True).upper()
                if len(code) > 100:
                    raise ValueError("车次超过 100 字符")
            except ValueError as exc:
                self.issue(row, str(exc))
                continue
            if (day, code) in seen:
                self.report["duplicates"] += 1
                continue
            seen.add((day, code))
            self.db.add(
                ManualSuspension(
                    typhoon_id=event,
                    departure_date=day,
                    raw_train_no=code,
                    batch_id=self.batch.id,
                    source_row=row["_row"],
                )
            )
            self.report["inserted"] += 1
        self.db.flush()
        registration = self.db.scalar(
            select(ResearchEvent).where(ResearchEvent.typhoon_id == event)
        )
        if registration and seen:
            dates = [day for day, _ in seen]
            registration.start_time = min(
                registration.start_time, datetime.combine(min(dates), time.min, TZ)
            )
            registration.end_time = max(
                registration.end_time, datetime.combine(max(dates), time(23, 59, 59), TZ)
            )
