from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Dataset, MetricRegistry
from app.services.metrics_registry import DEFAULT_METRICS


def ensure_dataset(db: Session, dataset_id: str, data_mode: str, name: str | None = None) -> Dataset:
    ds = db.get(Dataset, dataset_id)
    if ds:
        return ds
    ds = Dataset(
        id=dataset_id,
        name=name or dataset_id,
        data_mode=data_mode,
        description="demo seed dataset" if data_mode == "demo" else "real import dataset",
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def ensure_metrics(db: Session) -> None:
    for m in DEFAULT_METRICS:
        existing = db.get(MetricRegistry, m["id"])
        if existing:
            continue
        db.add(
            MetricRegistry(
                id=m["id"],
                name=m["name"],
                dimension=m["dimension"],
                unit=m["unit"],
                description=m.get("description"),
                aggregation=m.get("aggregation", "sum"),
                version="v1",
                active=True,
            )
        )
    db.commit()
