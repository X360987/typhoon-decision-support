from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.seed_adapter import SeedAdapter
from app.config import get_settings
from app.models import (
    Account,
    DataBatch,
    Event,
    ForecastPoint,
    ForecastSnapshot,
    HazardObservation,
    TrainStop,
    TrainSuspension,
    WeiboRaw,
)
from app.services.bootstrap import ensure_dataset, ensure_metrics
from app.services.pipeline import run_full_pipeline


def seed_demo_dataset(db: Session, seed: int | None = None) -> dict[str, Any]:
    settings = get_settings()
    seed = settings.seed_random_seed if seed is None else seed
    dataset_id = settings.default_dataset_id
    ensure_dataset(db, dataset_id, "demo", "模拟演示数据集")
    ensure_metrics(db)

    existing = db.query(Event).filter(Event.dataset_id == dataset_id).count()
    if existing:
        return {"status": "already_seeded", "dataset_id": dataset_id, "events": existing}

    adapter = SeedAdapter(seed=seed)
    batch = DataBatch(
        dataset_id=dataset_id,
        source_type="seed",
        status="running",
        file_name=f"seed-{seed}",
        idempotency_key=f"seed-{dataset_id}-{seed}",
        report={"seed": seed},
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    event_map: dict[str, Event] = {}
    for rec in adapter.iter_records("events"):
        ev = Event(
            dataset_id=dataset_id,
            event_code=rec["event_code"],
            name=rec["name"],
            external_typhoon_id=rec.get("external_typhoon_id"),
            start_time=rec["start_time"],
            end_time=rec["end_time"],
            status=rec.get("status", "historical"),
            config_version="v1",
            source_refs={"adapter": "seed"},
        )
        db.add(ev)
        db.flush()
        event_map[rec["event_code"]] = ev

    for rec in adapter.iter_records("accounts"):
        db.add(
            Account(
                dataset_id=dataset_id,
                user_id=rec["user_id"],
                nickname=rec["nickname"],
                account_class=rec["account_class"],
                verified=rec.get("verified", False),
                verify_type=rec.get("verify_type"),
                checklist_source=rec.get("checklist_source"),
                home_province=rec.get("home_province"),
            )
        )

    for rec in adapter.iter_records("timetable"):
        db.add(
            TrainStop(
                dataset_id=dataset_id,
                record_no=rec["record_no"],
                train_code=rec["train_code"],
                timetable_version=rec["timetable_version"],
                stop_order=rec["stop_order"],
                station_name=rec["station_name"],
                city=rec.get("city"),
                province_code=rec["province_code"],
                arrive_time=rec.get("arrive_time"),
                depart_time=rec.get("depart_time"),
                passenger_service=rec.get("passenger_service", True),
                passenger_flag_note=rec.get("passenger_flag_note"),
            )
        )

    weibo_count = 0
    ingested_at = datetime.utcnow()
    for rec in adapter.iter_records("weibo"):
        ev = event_map[rec["event_code"]]
        payload = {k: v for k, v in rec.items() if not k.startswith("_")}
        db.add(
            WeiboRaw(
                dataset_id=dataset_id,
                event_id=ev.id,
                batch_id=batch.id,
                source_id=rec["source_id"],
                bid=rec.get("bid"),
                user_id=rec["user_id"],
                nickname=rec.get("nickname"),
                content=rec["content"],
                publish_location=rec.get("publish_location"),
                topics=rec.get("topics"),
                reposts=rec.get("reposts"),
                comments=rec.get("comments"),
                likes=rec.get("likes"),
                published_at=rec.get("published_at"),
                ip=rec.get("ip"),
                verify_type=rec.get("verify_type"),
                heat=rec.get("heat"),
                stage=rec.get("stage"),
                raw_payload=payload,
                available_at=rec.get("available_at"),
                ingested_at=ingested_at,
            )
        )
        weibo_count += 1

    sus_count = 0
    for rec in adapter.iter_records("suspensions"):
        ev = event_map[rec["event_code"]]
        db.add(
            TrainSuspension(
                dataset_id=dataset_id,
                event_id=ev.id,
                batch_id=batch.id,
                record_no=rec["record_no"],
                suspension_date=rec["suspension_date"],
                train_code=rec["train_code"],
                train_db_id=rec.get("train_db_id"),
                train_type=rec.get("train_type"),
                scope=rec.get("scope"),
                segment_start=rec.get("segment_start"),
                segment_end=rec.get("segment_end"),
                scope_basis=rec.get("scope_basis"),
                notice_source_type=rec.get("notice_source_type"),
                notice_account=rec.get("notice_account"),
                confidence=rec.get("confidence"),
                evidence_text=rec.get("evidence_text"),
                match_method=rec.get("match_method"),
                merged_source_count=rec.get("merged_source_count", 1),
                known_at=rec.get("known_at"),
                raw_payload={"force_province": rec.get("force_province")},
            )
        )
        sus_count += 1

    for rec in adapter.iter_records("hazards"):
        ev = event_map[rec["event_code"]]
        db.add(
            HazardObservation(
                dataset_id=dataset_id,
                event_id=ev.id,
                observed_at=rec["observed_at"],
                arrived_at=rec.get("arrived_at"),
                province_code=rec.get("province_code"),
                metric=rec["metric"],
                value=rec.get("value"),
                unit=rec.get("unit"),
                source=rec["source"],
                original_granularity=rec.get("original_granularity"),
                quality_flags=rec.get("quality_flags"),
                raw_payload=rec,
            )
        )

    for rec in adapter.iter_records("forecasts"):
        ev = event_map[rec["event_code"]]
        snap = ForecastSnapshot(
            dataset_id=dataset_id,
            event_id=ev.id,
            source=rec["source"],
            issued_at=rec["issued_at"],
            arrived_at=rec["arrived_at"],
            revision=rec.get("revision", 1),
            raw_payload=rec.get("raw_payload"),
        )
        db.add(snap)
        db.flush()
        for pt in rec.get("points", []):
            db.add(
                ForecastPoint(
                    snapshot_id=snap.id,
                    dataset_id=dataset_id,
                    event_id=ev.id,
                    valid_time=pt["valid_time"],
                    lead_hours=pt["lead_hours"],
                    lat=pt.get("lat"),
                    lon=pt.get("lon"),
                    metric=pt["metric"],
                    value=pt.get("value"),
                    unit=pt.get("unit"),
                    version="v1",
                    province_code=pt.get("province_code"),
                    path_distance_proxy=pt.get("path_distance_proxy"),
                )
            )

    batch.status = "success"
    batch.completed_at = datetime.utcnow()
    batch.event_id = next(iter(event_map.values())).id
    batch.report = {
        "seed": seed,
        "weibo": weibo_count,
        "suspensions": sus_count,
        "events": list(event_map.keys()),
        "data_mode": "demo",
    }
    db.commit()

    pipeline_report = run_full_pipeline(db, dataset_id, trigger="seed")
    return {
        "status": "ok",
        "dataset_id": dataset_id,
        "batch_id": batch.id,
        "events": list(event_map.keys()),
        "pipeline": pipeline_report,
    }
