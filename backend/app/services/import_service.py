from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DataBatch, Event, ImportErrorRow, WeiboRaw
from app.services.bootstrap import ensure_dataset, ensure_metrics
from app.services.pipeline import run_full_pipeline

WEIBO_REQUIRED = ["source_id", "user_id", "content", "published_at"]
WEIBO_INT_FIELDS = ["reposts", "comments", "likes"]
ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}
ERROR_POLICIES = ("strict", "skip_errors")

# Entities that have an import path today; the rest are listed so the UI can show them as not connected.
IMPORT_SOURCES = [
    {"entity": "weibo", "name": "微博（个人与官方）", "status": "supported", "template": "weibo_template.csv"},
    {"entity": "accounts", "name": "账号核验清单", "status": "not_connected"},
    {"entity": "suspensions", "name": "停运公告", "status": "not_connected"},
    {"entity": "timetable", "name": "列车时刻表", "status": "not_connected"},
    {"entity": "hazard", "name": "台风实况", "status": "not_connected"},
    {"entity": "forecast", "name": "预报快照", "status": "not_connected"},
]

_process_secret = secrets.token_hex(32)


class ImportRejected(Exception):
    def __init__(self, code: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra or {}


def _parse_time(v: Any) -> datetime | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v
    try:
        ts = pd.to_datetime(v)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.to_pydatetime().replace(tzinfo=None)


def _is_blank(v: Any) -> bool:
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and not v.strip())


def _parse_int(v: Any) -> tuple[int | None, bool]:
    """Return (value, ok). Blank is allowed and yields None."""
    if _is_blank(v):
        return None, True
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None, False
    if f < 0 or f != int(f):
        return None, False
    return int(f), True


def file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_frame(path: Path, column_mapping: dict[str, str] | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ImportRejected("bad_format", f"格式不允许: {suffix}")
    try:
        df = pd.read_csv(path) if suffix == ".csv" else pd.read_excel(path)
    except Exception as exc:  # noqa: BLE001
        raise ImportRejected("unreadable", f"文件无法解析: {exc}") from exc
    if column_mapping:
        df = df.rename(columns=column_mapping)
    return df


def validate_frame(df: pd.DataFrame, entity: str) -> dict[str, Any]:
    """Row-level validation shared by precheck and commit."""
    report: dict[str, Any] = {
        "ok": True,
        "entity": entity,
        "rows": int(len(df)),
        "columns": [str(c) for c in df.columns],
        "missing_rate": {str(c): float(df[c].isna().mean()) for c in df.columns},
        "duplicate_rate": 0.0,
        "time_range": None,
        "error_rows": [],
        "blocking_errors": 0,
        "duplicates": 0,
        "warnings": 0,
        "province_coverage": {},
        "checks": [],
        "preview": [],
    }
    if entity != "weibo":
        report["ok"] = False
        report["error"] = "entity_not_connected"
        report["message"] = f"{entity} 导入未接入"
        return report
    missing_cols = [c for c in WEIBO_REQUIRED if c not in df.columns]
    report["checks"].append(
        {"name": "必填字段", "status": "fail" if missing_cols else "pass", "detail": f"缺少 {missing_cols}" if missing_cols else "齐全"}
    )
    if missing_cols:
        report["ok"] = False
        report["error"] = "missing_columns"
        report["message"] = f"缺少字段: {missing_cols}"
        return report

    seen: set[str] = set()
    times: list[datetime] = []
    bad_time = bad_num = untrusted = dup = 0
    for i, row in df.iterrows():
        line = int(i) + 2
        reasons: list[str] = []
        warnings: list[str] = []
        blocking = False
        is_dup = False
        sid = row.get("source_id")
        if _is_blank(sid):
            reasons.append("source_id 缺失")
            blocking = True
        elif str(sid) in seen:
            reasons.append("文件内重复 source_id，后出现的行不导入")
            is_dup = True
            dup += 1
        else:
            seen.add(str(sid))
        for col in ("user_id", "content"):
            if _is_blank(row.get(col)):
                reasons.append(f"{col} 缺失")
                blocking = True
        pt = _parse_time(row.get("published_at"))
        if pt is None:
            reasons.append("published_at 无法解析")
            bad_time += 1
            blocking = True
        else:
            times.append(pt)
        if "available_at" in df.columns and not _is_blank(row.get("available_at")):
            at = _parse_time(row.get("available_at"))
            if at is None:
                reasons.append("available_at 无法解析")
                bad_time += 1
                blocking = True
            elif pt is not None and at < pt:
                warnings.append("available_at 早于发布时间，不作为可信到达时间")
                untrusted += 1
        for col in WEIBO_INT_FIELDS:
            if col in df.columns:
                _, ok = _parse_int(row.get(col))
                if not ok:
                    reasons.append(f"{col} 不是非负整数")
                    bad_num += 1
                    blocking = True
        if reasons or warnings:
            report["error_rows"].append(
                {"row": line, "reasons": reasons + warnings, "blocking": blocking, "duplicate": is_dup}
            )
        if blocking:
            report["blocking_errors"] += 1
        if warnings and not reasons:
            report["warnings"] += 1
        if len(report["preview"]) < 50:
            report["preview"].append(
                {
                    "row": line,
                    "published_at": None if pt is None else pt.isoformat(),
                    "publish_location": None if _is_blank(row.get("publish_location")) else str(row.get("publish_location")),
                    "content": "" if _is_blank(row.get("content")) else str(row.get("content"))[:60],
                    "status": "error" if blocking else ("duplicate" if is_dup else ("warning" if warnings else "ok")),
                }
            )
    report["duplicates"] = dup
    report["duplicate_rate"] = dup / len(df) if len(df) else 0.0
    if times:
        report["time_range"] = {"start": min(times).isoformat(), "end": max(times).isoformat()}
    has_arrival = "available_at" in df.columns
    if "publish_location" in df.columns:
        report["province_coverage"] = {
            str(k): int(v) for k, v in df["publish_location"].fillna("UNKNOWN").value_counts().items()
        }
    report["checks"] += [
        {"name": "时间格式", "status": "fail" if bad_time else "pass", "detail": f"{bad_time} 处无法解析" if bad_time else "全部可解析"},
        {"name": "数值字段", "status": "fail" if bad_num else "pass", "detail": f"{bad_num} 处非法" if bad_num else "通过"},
        {
            "name": "到达时间",
            "status": "warn" if (not has_arrival or untrusted) else "pass",
            "detail": "缺少 available_at 列，导入后不能严格回放" if not has_arrival else (f"{untrusted} 行早于发布时间" if untrusted else "可用于当时已知回放"),
        },
        {
            "name": "地区覆盖",
            "status": "warn" if "UNKNOWN" in report["province_coverage"] else "pass",
            "detail": f"{report['province_coverage'].get('UNKNOWN', 0)} 行无发布地" if report["province_coverage"] else "无 publish_location 列",
        },
        {"name": "重复记录", "status": "warn" if dup else "pass", "detail": f"{dup} 行重复" if dup else "无重复"},
    ]
    if report["blocking_errors"]:
        report["ok"] = False
        report["error"] = "row_errors"
        report["message"] = f"{report['blocking_errors']} 行存在阻断错误"
    return report


def _secret() -> bytes:
    settings = get_settings()
    return (settings.precheck_secret or settings.api_key or _process_secret).encode()


def _canonical(binding: dict[str, Any]) -> bytes:
    return json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def issue_token(binding: dict[str, Any]) -> str:
    payload = {**binding, "issued_at": datetime.utcnow().isoformat()}
    body = _canonical(payload)
    sig = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(body).decode() + "." + sig


def verify_token(token: str, binding: dict[str, Any]) -> None:
    try:
        body_b64, sig = token.rsplit(".", 1)
        body = base64.urlsafe_b64decode(body_b64.encode())
        payload = json.loads(body)
    except Exception as exc:  # noqa: BLE001
        raise ImportRejected("invalid_token", "预检凭证格式无效") from exc
    expected = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise ImportRejected("invalid_token", "预检凭证签名无效")
    issued = datetime.fromisoformat(payload.get("issued_at", "1970-01-01T00:00:00"))
    if datetime.utcnow() - issued > timedelta(minutes=get_settings().precheck_ttl_minutes):
        raise ImportRejected("token_expired", "预检凭证已过期，请重新预检")
    for key, value in binding.items():
        if payload.get(key) != value:
            raise ImportRejected("token_mismatch", f"预检凭证与提交内容不一致: {key}")


def precheck(
    path: Path,
    data: bytes,
    entity: str,
    dataset_id: str,
    event_id: int,
    column_mapping: dict[str, str] | None,
) -> dict[str, Any]:
    df = read_frame(path, column_mapping)
    report = validate_frame(df, entity)
    binding = {
        "file_hash": file_hash(data),
        "entity": entity,
        "dataset_id": dataset_id,
        "event_id": event_id,
        "mapping": column_mapping or {},
    }
    report["file_hash"] = binding["file_hash"]
    report["mapping_applied"] = column_mapping or {}
    blocking = report.get("error") in ("missing_columns", "entity_not_connected", "bad_format")
    report["precheck_token"] = None if blocking else issue_token(binding)
    report["allowed_policies"] = [] if blocking else (["strict"] if report["ok"] else ["skip_errors"])
    return report


def precheck_file(path: Path, entity: str, column_mapping: dict[str, str] | None = None) -> dict[str, Any]:
    """Validation only (no token); kept for scripts and tests."""
    try:
        return validate_frame(read_frame(path, column_mapping), entity)
    except ImportRejected as exc:
        return {"ok": False, "error": exc.code, "message": exc.message}


def commit_weibo_import(
    db: Session,
    dataset_id: str,
    event_id: int,
    path: Path,
    data: bytes,
    token: str,
    *,
    data_mode: str,
    column_mapping: dict[str, str] | None = None,
    error_policy: str = "strict",
    confirm_skip: bool = False,
    file_name: str | None = None,
) -> dict[str, Any]:
    if error_policy not in ERROR_POLICIES:
        raise ImportRejected("bad_policy", f"error_policy 仅支持 {ERROR_POLICIES}")
    digest = file_hash(data)
    verify_token(
        token,
        {"file_hash": digest, "entity": "weibo", "dataset_id": dataset_id, "event_id": event_id, "mapping": column_mapping or {}},
    )
    df = read_frame(path, column_mapping)
    report = validate_frame(df, "weibo")
    if report.get("error") == "missing_columns":
        raise ImportRejected("missing_columns", report["message"])
    blocking_rows = [e for e in report["error_rows"] if e["blocking"]]
    if blocking_rows and error_policy == "strict":
        raise ImportRejected("row_errors", f"{len(blocking_rows)} 行存在阻断错误，严格模式不允许导入", {"error_rows": blocking_rows})
    if blocking_rows and not confirm_skip:
        raise ImportRejected("confirm_required", "跳过错误行需要显式确认", {"error_rows": blocking_rows})

    ev = db.get(Event, event_id)
    if not ev or ev.dataset_id != dataset_id:
        raise ImportRejected("event_mismatch", "事件不存在或不属于该数据集")
    ensure_dataset(db, dataset_id, data_mode, dataset_id)
    ensure_metrics(db)

    key = f"import-{dataset_id}-{event_id}-{digest[:24]}-{error_policy}"
    batch = db.query(DataBatch).filter(DataBatch.dataset_id == dataset_id, DataBatch.idempotency_key == key).first()
    if batch and batch.status in ("imported", "success"):
        return {
            "ok": True,
            "import_status": "idempotent_reuse",
            "analysis_status": (batch.report or {}).get("analysis_status"),
            "batch_id": batch.id,
            "report": batch.report,
        }
    if batch is None:
        batch = DataBatch(dataset_id=dataset_id, event_id=event_id, source_type=path.suffix.lower().lstrip("."), idempotency_key=key)
        db.add(batch)
    batch.status = "running"
    batch.file_name = (file_name or path.name)[:255]
    batch.report = {k: v for k, v in report.items() if k != "preview"}
    db.commit()
    batch_id = batch.id

    excluded_lines = {e["row"] for e in blocking_rows}
    now = datetime.utcnow()
    inserted = skipped = 0
    try:
        db.query(ImportErrorRow).filter(ImportErrorRow.batch_id == batch_id).delete()
        seen: set[str] = set()
        existing = {
            s for (s,) in db.query(WeiboRaw.source_id).filter(WeiboRaw.dataset_id == dataset_id)
        }
        for i, row in df.iterrows():
            line = int(i) + 2
            payload = {str(k): (None if _is_blank(v) else (v.isoformat() if isinstance(v, datetime) else v)) for k, v in row.to_dict().items()}
            if line in excluded_lines:
                reasons = next(e["reasons"] for e in blocking_rows if e["row"] == line)
                db.add(ImportErrorRow(batch_id=batch_id, row_number=line, reason="; ".join(reasons), raw_payload=payload))
                continue
            sid = str(row.get("source_id"))
            if sid in seen or sid in existing:
                skipped += 1
                continue
            seen.add(sid)
            published_at = _parse_time(row.get("published_at"))
            available_at = _parse_time(row.get("available_at")) if "available_at" in df.columns else None

            def text(col: str) -> str | None:
                v = row.get(col)
                return None if _is_blank(v) else str(v)

            db.add(
                WeiboRaw(
                    dataset_id=dataset_id,
                    event_id=event_id,
                    batch_id=batch_id,
                    source_id=sid,
                    bid=text("bid"),
                    user_id=str(row.get("user_id")),
                    nickname=text("nickname"),
                    content=str(row.get("content")),
                    article_url=text("article_url"),
                    publish_location=text("publish_location"),
                    topics=text("topics"),
                    reposts=_parse_int(row.get("reposts"))[0] if "reposts" in df.columns else None,
                    comments=_parse_int(row.get("comments"))[0] if "comments" in df.columns else None,
                    likes=_parse_int(row.get("likes"))[0] if "likes" in df.columns else None,
                    published_at=published_at,
                    ip=text("ip"),
                    verify_type=text("verify_type"),
                    raw_payload=payload,
                    available_at=available_at,
                    ingested_at=now,
                )
            )
            inserted += 1
        batch = db.get(DataBatch, batch_id)
        batch.status = "imported"
        batch.completed_at = datetime.utcnow()
        batch.report = {
            **(batch.report or {}),
            "inserted": inserted,
            "skipped_duplicates": skipped,
            "excluded_rows": sorted(excluded_lines),
            "error_policy": error_policy,
        }
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        batch = db.get(DataBatch, batch_id)
        batch.status = "failed"
        batch.report = {**(batch.report or {}), "failure": str(exc)}
        db.commit()
        raise ImportRejected("import_failed", f"导入失败，已回滚，可重试: {exc}", {"batch_id": batch_id}) from exc

    pipeline = run_full_pipeline(db, dataset_id, event_id=event_id, trigger=f"import:{batch_id}")
    analysis_status = "success" if pipeline["ok"] else "failed"
    batch = db.get(DataBatch, batch_id)
    batch.report = {**(batch.report or {}), "analysis_status": analysis_status}
    db.commit()
    return {
        "ok": True,
        "import_status": "imported",
        "analysis_status": analysis_status,
        "batch_id": batch_id,
        "inserted": inserted,
        "skipped": skipped,
        "excluded_rows": [e for e in blocking_rows],
        "pipeline": pipeline,
    }
