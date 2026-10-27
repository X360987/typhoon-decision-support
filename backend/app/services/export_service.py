from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy.orm import Session

from app.models import Anomaly, AnomalyEvidence
from app.services.query_context import QueryContext, anomaly_query, metric_query, visible_metrics


def _csv_safe(value: Any) -> str:
    s = "" if value is None else str(value)
    if s.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + s
    return s


def export_anomalies_csv(db: Session, ctx: QueryContext) -> str:
    """Same filters and order as the anomaly list (newest hour first, then id)."""
    rows = anomaly_query(db, ctx).order_by(Anomaly.hour_bj.desc(), Anomaly.id.desc()).all()
    evidence_ids: dict[int, list[str]] = {}
    if rows:
        for e in db.query(AnomalyEvidence).filter(AnomalyEvidence.anomaly_id.in_([a.id for a in rows])):
            evidence_ids.setdefault(e.anomaly_id, []).append(str(e.id))
    meta = ctx.describe()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "anomaly_id",
            "data_mode",
            "dataset_id",
            "event_id",
            "data_version",
            "replay_mode",
            "as_of",
            "timezone",
            "analysis_scope",
            "dimensions",
            "anomaly_type",
            "province_code",
            "hour_bj",
            "available_at",
            "nature",
            "score",
            "baseline",
            "threshold",
            "quality_status",
            "rule_version",
            "group_key",
            "evidence_ids",
            "explanation",
            "filter_summary",
        ]
    )
    summary = ctx.summary_text()
    for a in rows:
        writer.writerow(
            [
                a.id,
                meta["data_mode"],
                _csv_safe(a.dataset_id),
                a.event_id,
                _csv_safe(a.data_version),
                meta["replay_mode"],
                meta["as_of"] or "",
                "Asia/Shanghai",
                a.analysis_scope,
                _csv_safe(",".join(a.dimensions or [])),
                _csv_safe(a.anomaly_type),
                a.province_code,
                a.hour_bj.isoformat(),
                a.available_at.isoformat() if a.available_at else "",
                a.nature,
                a.score,
                a.baseline,
                a.threshold,
                a.quality_status,
                _csv_safe(a.rule_version),
                _csv_safe(a.group_key),
                ";".join(evidence_ids.get(a.id, [])),
                _csv_safe(a.explanation),
                _csv_safe(summary),
            ]
        )
    return buf.getvalue()


def export_metrics_csv(db: Session, ctx: QueryContext) -> str:
    rows, _ = visible_metrics(db, ctx, metric_query(db, ctx, include_national=True))
    meta = ctx.describe()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "data_mode",
            "dataset_id",
            "event_id",
            "data_version",
            "replay_mode",
            "as_of",
            "timezone",
            "province_code",
            "hour_bj",
            "metric_id",
            "value",
            "sample_size",
            "quality_status",
            "available_at",
        ]
    )
    for m in rows:
        writer.writerow(
            [
                meta["data_mode"],
                m.dataset_id,
                m.event_id,
                m.version,
                meta["replay_mode"],
                meta["as_of"] or "",
                "Asia/Shanghai",
                m.province_code,
                m.hour_bj.isoformat(),
                m.metric_id,
                m.value,
                m.sample_size,
                m.quality_status,
                m.available_at.isoformat() if m.available_at else "",
            ]
        )
    return buf.getvalue()
