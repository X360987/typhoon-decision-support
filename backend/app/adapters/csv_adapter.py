from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from app.adapters.base import DataSourceAdapter


class CsvXlsxAdapter(DataSourceAdapter):
    name = "csv_xlsx"

    def __init__(self, path: str | Path, entity: str, column_mapping: dict[str, str] | None = None):
        self.path = Path(path)
        self.entity = entity
        self.column_mapping = column_mapping or {}

    def _read(self) -> pd.DataFrame:
        suffix = self.path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(self.path)
        elif suffix == ".csv":
            df = pd.read_csv(self.path)
        else:
            raise ValueError(f"unsupported_format:{suffix}")
        if self.column_mapping:
            df = df.rename(columns=self.column_mapping)
        return df

    def iter_records(self, entity: str | None = None) -> Iterator[dict[str, Any]]:
        target = entity or self.entity
        if target != self.entity:
            return
        df = self._read()
        for _, row in df.iterrows():
            rec = {k: (None if pd.isna(v) else v) for k, v in row.to_dict().items()}
            yield rec
