"""预览和正式提交共用同一导入实现。"""

from sqlalchemy.exc import DataError, IntegrityError

from app.importers.catalog import CatalogImporter
from app.importers.manual import ManualImporter
from app.importers.rail import RailImporter
from app.importers.weibo import WeiboImporter


class ImportProcessor(WeiboImporter, RailImporter, ManualImporter, CatalogImporter):
    """同一业务实现供预览和正式提交共用，避免两套规则逐渐分歧。"""

    def __init__(self, db, batch, decisions=None):
        self.db, self.batch = db, batch
        self.decisions = decisions or {}
        self.report = {
            "input_rows": len(batch.rows),
            "inserted": 0,
            "updated": 0,
            "duplicates": 0,
            "errors": [],
            "warnings": [],
        }

    def issue(self, row, reason, train_no=None, warning=False, **details):
        """错误总是携带原始行号、工作表及拆分后的车次。"""
        item = {
            "row": row["_row"],
            "sheet": row.get("_sheet", ""),
            "train_no": train_no,
            "reason": reason,
            **details,
        }
        self.report["warnings" if warning else "errors"].append(item)

    def run(self):
        if self.batch.kind == "rail_manual":
            self.manual_rail()
        elif self.batch.kind == "rail":
            self.rail()
        else:
            method = {"weibo": self.weibo, "trains": self.train, "stations": self.station}[
                self.batch.kind
            ]
            for row in self.batch.rows:
                before_counts = {k: self.report[k] for k in ("inserted", "updated", "duplicates")}
                try:
                    # 单行失败回滚这一行，不留下孤立账号或部分字段修改。
                    with self.db.begin_nested():
                        method(row)
                        self.db.flush()
                except (ValueError, TypeError) as exc:
                    self.report.update(before_counts)
                    self.issue(row, str(exc))
                except (DataError, IntegrityError):
                    self.report.update(before_counts)
                    self.issue(row, "字段长度、类型或数据库约束不满足，该行已回滚")
        self.report["error_count"] = len(self.report["errors"])
        return self.report
