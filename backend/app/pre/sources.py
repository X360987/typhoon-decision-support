"""场景：灾前。账号、停运、时刻表、实况和预报走与微博相同的预检和幂等提交。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models import (
    Account,
    DataBatch,
    ForecastPoint,
    ForecastSnapshot,
    HazardObservation,
    ImportErrorRow,
    TrainStop,
    TrainSuspension,
)
from app.services.import_service import (
    ERROR_POLICIES,
    ImportRejected,
    _is_blank,
    _parse_int,
    _parse_time,
    file_hash,
    verify_token,
)

SPECS: dict[str, dict[str, Any]] = {
    "accounts": {"required": ["user_id", "nickname", "account_class"], "times": []},
    "suspensions": {"required": ["record_no", "suspension_date", "train_code"], "times": ["suspension_date"]},
    "timetable": {
        "required": ["record_no", "train_code", "timetable_version", "stop_order", "station_name", "province_code"],
        "times": [],
    },
    "hazard": {"required": ["observed_at", "metric", "source"], "times": ["observed_at"]},
    "forecast": {"required": ["issued_at", "arrived_at", "valid_time", "metric"], "times": ["issued_at", "arrived_at", "valid_time"]},
}


def validate_table(df: pd.DataFrame, entity: str) -> dict[str, Any]:
    spec = SPECS[entity]
    report: dict[str, Any] = {
        "ok": True,
        "entity": entity,
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "missing_rate": {str(c): float(df[c].isna().mean()) if len(df) else 0.0 for c in df.columns},
        "duplicate_rate": 0.0,
        "time_range": None,
        "error_rows": [],
        "blocking_errors": 0,
        "duplicates": 0,
        "warnings": 0,
        "province_coverage": {},
        "checks": [],
        "preview": [],
        "completeness": 1.0,
        "time_anomaly_rate": 0.0,
        "geo_coverage": None,
    }
    missing_cols = [c for c in spec["required"] if c not in df.columns]
    report["checks"].append(
        {"name": "必填字段", "status": "fail" if missing_cols else "pass", "detail": f"缺少 {missing_cols}" if missing_cols else "齐全"}
    )
    if missing_cols:
        report["ok"] = False
        report["error"] = "missing_columns"
        report["message"] = f"缺少字段: {missing_cols}"
        return report
    bad_time = 0
    times: list[datetime] = []
    for i, row in df.iterrows():
        line = int(i) + 2
        reasons: list[str] = []
        for col in spec["required"]:
            if col in spec["times"]:
                parsed = _parse_time(row.get(col))
                if parsed is None:
                    reasons.append(f"{col} 无法解析")
                    bad_time += 1
                else:
                    times.append(parsed)
            elif _is_blank(row.get(col)):
                reasons.append(f"{col} 缺失")
        if entity == "accounts" and not _is_blank(row.get("account_class")) and str(row.get("account_class")) not in ("personal", "official", "unknown"):
            reasons.append("account_class 仅支持 personal、official、unknown")
        if reasons:
            report["error_rows"].append({"row": line, "reasons": reasons, "blocking": True, "duplicate": False})
            report["blocking_errors"] += 1
        if len(report["preview"]) < 50:
            report["preview"].append({"row": line, "status": "error" if reasons else "ok"})
    rows_n = len(df) or 1
    report["completeness"] = 1 - (report["blocking_errors"] / rows_n)
    report["time_anomaly_rate"] = bad_time / rows_n
    if times:
        report["time_range"] = {"start": min(times).isoformat(), "end": max(times).isoformat()}
    if report["blocking_errors"]:
        report["ok"] = False
        report["error"] = "row_errors"
        report["message"] = f"{report['blocking_errors']} 行存在阻断错误"
    return report


def _text(row: pd.Series, col: str) -> str | None:
    value = row.get(col)
    return None if _is_blank(value) else str(value)


def commit_table_import(
    db: Session,
    dataset_id: str,
    event_id: int,
    df: pd.DataFrame,
    data: bytes,
    token: str,
    *,
    entity: str,
    column_mapping: dict[str, str] | None,
    error_policy: str,
    confirm_skip: bool,
    file_name: str | None,
) -> dict[str, Any]:
    if entity not in SPECS:
        raise ImportRejected("entity_not_connected", f"{entity} 导入未接入")
    if error_policy not in ERROR_POLICIES:
        raise ImportRejected("bad_policy", f"error_policy 仅支持 {ERROR_POLICIES}")
    digest = file_hash(data)
    verify_token(
        token,
        {"file_hash": digest, "entity": entity, "dataset_id": dataset_id, "event_id": event_id, "mapping": column_mapping or {}},
    )
    report = validate_table(df, entity)
    if report.get("error") == "missing_columns":
        raise ImportRejected("missing_columns", report["message"])
    blocking_rows = [row for row in report["error_rows"] if row["blocking"]]
    if blocking_rows and error_policy == "strict":
        raise ImportRejected("row_errors", f"{len(blocking_rows)} 行存在阻断错误，严格模式不允许导入", {"error_rows": blocking_rows})
    if blocking_rows and not confirm_skip:
        raise ImportRejected("confirm_required", "跳过错误行需要显式确认", {"error_rows": blocking_rows})
    key = f"import-{entity}-{dataset_id}-{event_id}-{digest[:24]}-{error_policy}"
    batch = db.query(DataBatch).filter(DataBatch.dataset_id == dataset_id, DataBatch.idempotency_key == key).first()
    if batch and batch.status in ("imported", "success"):
        return {"ok": True, "import_status": "idempotent_reuse", "batch_id": batch.id, "report": batch.report}
    if batch is None:
        batch = DataBatch(dataset_id=dataset_id, event_id=event_id, source_type=entity, idempotency_key=key)
        db.add(batch)
    batch.status = "running"
    batch.file_name = (file_name or entity)[:255]
    batch.report = {k: v for k, v in report.items() if k != "preview"}
    db.commit()
    excluded = {row["row"] for row in blocking_rows}
    inserted = 0
    snapshots: dict[tuple[datetime, datetime], ForecastSnapshot] = {}
    for i, row in df.iterrows():
        line = int(i) + 2
        if line in excluded:
            db.add(ImportErrorRow(batch_id=batch.id, row_number=line, reason="阻断错误", raw_payload={}))
            continue
        if entity == "accounts":
            user_id = str(row.get("user_id"))
            existing = db.query(Account).filter(Account.dataset_id == dataset_id, Account.user_id == user_id).first()
            target = existing or Account(dataset_id=dataset_id, user_id=user_id, nickname=str(row.get("nickname")), account_class=str(row.get("account_class")))
            target.nickname = str(row.get("nickname"))
            target.account_class = str(row.get("account_class"))
            target.verified = str(row.get("verified") or "").lower() in ("1", "true", "yes")
            target.verify_type = _text(row, "verify_type")
            target.home_province = _text(row, "home_province")
            if existing is None:
                db.add(target)
        elif entity == "suspensions":
            record_no = str(row.get("record_no"))
            if db.query(TrainSuspension).filter(TrainSuspension.dataset_id == dataset_id, TrainSuspension.record_no == record_no).first():
                continue
            db.add(
                TrainSuspension(
                    dataset_id=dataset_id,
                    event_id=event_id,
                    batch_id=batch.id,
                    record_no=record_no,
                    suspension_date=_parse_time(row.get("suspension_date")),
                    train_code=str(row.get("train_code")),
                    scope=_text(row, "scope"),
                    segment_start=_text(row, "segment_start"),
                    segment_end=_text(row, "segment_end"),
                    known_at=_parse_time(row.get("known_at")) if "known_at" in df.columns else None,
                )
            )
        elif entity == "timetable":
            order, ok = _parse_int(row.get("stop_order"))
            if not ok or order is None:
                continue
            db.add(
                TrainStop(
                    dataset_id=dataset_id,
                    record_no=str(row.get("record_no")),
                    train_code=str(row.get("train_code")),
                    timetable_version=str(row.get("timetable_version")),
                    stop_order=order,
                    station_name=str(row.get("station_name")),
                    province_code=str(row.get("province_code")),
                    city=_text(row, "city"),
                    arrive_time=_text(row, "arrive_time"),
                    depart_time=_text(row, "depart_time"),
                )
            )
        elif entity == "hazard":
            db.add(
                HazardObservation(
                    dataset_id=dataset_id,
                    event_id=event_id,
                    observed_at=_parse_time(row.get("observed_at")),
                    arrived_at=_parse_time(row.get("arrived_at")) if "arrived_at" in df.columns else None,
                    province_code=_text(row, "province_code"),
                    metric=str(row.get("metric")),
                    value=None if _is_blank(row.get("value")) else float(row.get("value")),
                    unit=_text(row, "unit"),
                    source=str(row.get("source")),
                )
            )
        else:
            issued = _parse_time(row.get("issued_at"))
            arrived = _parse_time(row.get("arrived_at"))
            snap = snapshots.get((issued, arrived))
            if snap is None:
                snap = ForecastSnapshot(dataset_id=dataset_id, event_id=event_id, source="import", issued_at=issued, arrived_at=arrived)
                db.add(snap)
                db.flush()
                snapshots[(issued, arrived)] = snap
            lead, ok = _parse_int(row.get("lead_hours")) if "lead_hours" in df.columns else (None, True)
            db.add(
                ForecastPoint(
                    snapshot_id=snap.id,
                    dataset_id=dataset_id,
                    event_id=event_id,
                    valid_time=_parse_time(row.get("valid_time")),
                    lead_hours=lead or 0,
                    metric=str(row.get("metric")),
                    value=None if _is_blank(row.get("value")) else float(row.get("value")),
                    unit=_text(row, "unit"),
                    province_code=_text(row, "province_code"),
                )
            )
        inserted += 1
    batch.status = "imported"
    batch.completed_at = datetime.utcnow()
    batch.report = {**(batch.report or {}), "inserted": inserted}
    db.commit()
    return {"ok": True, "import_status": "imported", "batch_id": batch.id, "inserted": inserted, "report": batch.report}
