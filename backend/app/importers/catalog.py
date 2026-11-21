"""年度车次目录和车站坐标。相同站名的不同坐标不覆盖。"""

from sqlalchemy import select

from app.importers.ids import split_train
from app.importers.reader import identifier, value
from app.models import Station, Train


class CatalogImporter:
    def train(self, row):
        year = int(value(row, "年份", "catalog_year") or self.batch.catalog_year or row["_sheet"])
        if not 1900 <= year <= 2100:
            raise ValueError("目录年份超出允许范围")
        no = value(row, "车次", "train_no", required=True).upper()
        if len(split_train(no)) != 1:
            raise ValueError("年度目录车次必须为单个标准车次")
        sid = identifier(value(row, "ID", "source_train_id", required=True))
        found = self.db.scalar(select(Train).where(Train.year == year, Train.train_no == no))
        other = self.db.scalar(
            select(Train).where(Train.year == year, Train.source_train_id == sid)
        )
        if found or other:
            if found is not None and found is other:
                self.report["duplicates"] += 1
                return
            raise ValueError("年度目录 ID 或车次与已有记录冲突，不覆盖")
        self.db.add(Train(year=year, source_train_id=sid, train_no=no))
        self.report["inserted"] += 1

    def station(self, row):
        name = value(row, "站名", "name", required=True)
        lon = float(value(row, "经度", "longitude", required=True))
        lat = float(value(row, "纬度", "latitude", required=True))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("坐标超出范围")
        if value(row, "坐标系", "crs", required=True).upper() != "WGS84":
            raise ValueError("当前仅接受明确标注 WGS84 的坐标，不自动转换")
        old = self.db.get(Station, name)
        if old:
            if (old.longitude, old.latitude) != (lon, lat):
                raise ValueError("站点坐标冲突，不自动覆盖")
            self.report["duplicates"] += 1
        else:
            self.db.add(Station(name=name, longitude=lon, latitude=lat))
            self.report["inserted"] += 1
