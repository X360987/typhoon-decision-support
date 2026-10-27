from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Event
from app.services.prediction_service import build_readiness_report, run_predictions, train_demo_models
from app.services.seed_service import seed_demo_dataset


def seed_and_prepare_demo(db: Session) -> dict[str, Any]:
    """Seed the simulated dataset, run the single-event model experiment and one default prediction."""
    result = seed_demo_dataset(db)
    out: dict[str, Any] = {"seed": result, "train": None, "prediction": None}
    if result.get("status") != "ok":
        return out
    events = db.query(Event).filter(Event.dataset_id == result["dataset_id"]).order_by(Event.id).all()
    if not events:
        return out
    ev = events[0]
    out["train"] = train_demo_models(db, result["dataset_id"], ev.id)
    build_readiness_report(db, result["dataset_id"])
    # Origin late in the event so the default view can show the h3 model once its training cutoff has passed.
    origin = (ev.start_time + (ev.end_time - ev.start_time) * 5 / 6).replace(minute=0, second=0, microsecond=0)
    out["prediction"] = run_predictions(db, result["dataset_id"], ev.id, origin, data_mode="demo")
    return out
