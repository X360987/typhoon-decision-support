from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator


class DataSourceAdapter(ABC):
    """Unified ingestion adapter. Seed and CSV share the same validate/normalize path."""

    name: str

    @abstractmethod
    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        raise NotImplementedError


class ForecastProvider(ABC):
    name: str

    @abstractmethod
    def fetch_snapshots(self, event_code: str) -> list[dict[str, Any]]:
        raise NotImplementedError
