from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Dataset(Base):
    __tablename__ = "dataset"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    data_mode: Mapped[str] = mapped_column(String(16))  # demo | real
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Event(Base):
    __tablename__ = "event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), ForeignKey("dataset.id"), index=True)
    event_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    external_typhoon_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(32), default="historical")  # tracking|historical
    config_version: Mapped[str] = mapped_column(String(64), default="v1")
    source_refs: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("dataset_id", "event_code", name="uq_event_dataset_code"),)


class Account(Base):
    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), ForeignKey("dataset.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[str] = mapped_column(String(128))
    account_class: Mapped[str] = mapped_column(String(32))  # personal | official
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verify_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    checklist_source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    home_province: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    __table_args__ = (UniqueConstraint("dataset_id", "user_id", name="uq_account_dataset_user"),)


class DataBatch(Base):
    __tablename__ = "data_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), ForeignKey("dataset.id"), index=True)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("event.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32))  # seed|csv|xlsx|api
    status: Mapped[str] = mapped_column(String(32), default="pending")
    file_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "idempotency_key", name="uq_batch_idempotency"),
        Index("ix_batch_status", "dataset_id", "status"),
    )


class ImportErrorRow(Base):
    __tablename__ = "import_error"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer, ForeignKey("data_batch.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class WeiboRaw(Base):
    __tablename__ = "weibo_raw"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("data_batch.id"), nullable=True)
    source_id: Mapped[str] = mapped_column(String(64))
    bid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str] = mapped_column(String(64))
    nickname: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    article_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    publish_location: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    at_users: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    topics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reposts: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    publish_tool: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    image_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    video_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retweet_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verify_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    verify_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    member_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    member_level: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    heat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    stage: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ingested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "source_id", name="uq_weibo_raw_source"),
        Index("ix_weibo_raw_event_time", "dataset_id", "event_id", "published_at"),
    )


class WeiboClean(Base):
    __tablename__ = "weibo_clean"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    weibo_raw_id: Mapped[int] = mapped_column(Integer, ForeignKey("weibo_raw.id"))
    user_id: Mapped[str] = mapped_column(String(64))
    account_class: Mapped[str] = mapped_column(String(32))
    published_at: Mapped[datetime] = mapped_column(DateTime)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    hour_bj: Mapped[datetime] = mapped_column(DateTime, index=True)
    sentiment_label: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sentiment_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sentiment_model_version: Mapped[str] = mapped_column(String(64), default="demo-rule-v1")
    interaction: Mapped[int] = mapped_column(Integer, default=0)
    is_help_request: Mapped[bool] = mapped_column(Boolean, default=False)
    topics: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    publisher_home_province: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    quality_flags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class WeiboRegion(Base):
    __tablename__ = "weibo_region"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    weibo_clean_id: Mapped[int] = mapped_column(Integer, ForeignKey("weibo_clean.id"))
    province_code: Mapped[str] = mapped_column(String(16))
    attribution_method: Mapped[str] = mapped_column(String(64))
    is_unique_count: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (
        UniqueConstraint("weibo_clean_id", "province_code", name="uq_weibo_region"),
        Index("ix_weibo_region_lookup", "dataset_id", "event_id", "province_code"),
    )


class TrainStop(Base):
    __tablename__ = "train_stop"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    record_no: Mapped[str] = mapped_column(String(64))
    train_code: Mapped[str] = mapped_column(String(32))
    timetable_version: Mapped[str] = mapped_column(String(64))
    stop_order: Mapped[int] = mapped_column(Integer)
    station_name: Mapped[str] = mapped_column(String(128))
    city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    province_code: Mapped[str] = mapped_column(String(16))
    arrive_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    depart_time: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    passenger_service: Mapped[bool] = mapped_column(Boolean, default=True)
    passenger_flag_note: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    valid_to: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "train_code", "timetable_version", "stop_order", name="uq_train_stop"
        ),
    )


class TrainSuspension(Base):
    __tablename__ = "train_suspension"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    batch_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("data_batch.id"), nullable=True)
    record_no: Mapped[str] = mapped_column(String(64))
    suspension_date: Mapped[datetime] = mapped_column(DateTime)
    train_code: Mapped[str] = mapped_column(String(32))
    train_db_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    train_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    scope: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    segment_start: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    segment_end: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    scope_basis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notice_source_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notice_account: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    notice_weibo_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    notice_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    match_method: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    merged_source_count: Mapped[int] = mapped_column(Integer, default=1)
    known_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint("dataset_id", "record_no", name="uq_suspension_record"),
        Index("ix_suspension_event", "dataset_id", "event_id", "suspension_date"),
    )


class SuspensionRegionHour(Base):
    __tablename__ = "suspension_region_hour"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    suspension_id: Mapped[int] = mapped_column(Integer, ForeignKey("train_suspension.id"))
    province_code: Mapped[str] = mapped_column(String(16))
    hour_bj: Mapped[datetime] = mapped_column(DateTime)
    train_code: Mapped[str] = mapped_column(String(32))
    estimate_basis: Mapped[str] = mapped_column(String(128))
    run_key: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)
    stations: Mapped[Optional[list[Any]]] = mapped_column(JSON, nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "event_id",
            "suspension_id",
            "province_code",
            "hour_bj",
            "train_code",
            name="uq_suspension_region_hour",
        ),
    )


class HazardObservation(Base):
    __tablename__ = "hazard_observation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    arrived_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    province_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    original_granularity: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    quality_flags: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)


class MetricRegistry(Base):
    __tablename__ = "metric_registry"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    dimension: Mapped[str] = mapped_column(String(32))  # social|organizational|physical|hazard
    unit: Mapped[str] = mapped_column(String(32))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    aggregation: Mapped[str] = mapped_column(String(64), default="sum")
    version: Mapped[str] = mapped_column(String(32), default="v1")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProvinceHourMetric(Base):
    __tablename__ = "province_hour_metric"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"))
    province_code: Mapped[str] = mapped_column(String(16))
    hour_bj: Mapped[datetime] = mapped_column(DateTime)
    metric_id: Mapped[str] = mapped_column(String(64), ForeignKey("metric_registry.id"))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sample_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    coverage: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(32), default="ok")
    version: Mapped[str] = mapped_column(String(64), default="v1")
    data_batch_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    computed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "event_id",
            "province_code",
            "hour_bj",
            "metric_id",
            "version",
            name="uq_province_hour_metric",
        ),
        Index("ix_phm_query", "dataset_id", "event_id", "province_code", "hour_bj"),
    )


class Anomaly(Base):
    __tablename__ = "anomaly"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    analysis_scope: Mapped[str] = mapped_column(String(16))  # single|pair|joint
    dimensions: Mapped[list[Any]] = mapped_column(JSON)
    anomaly_type: Mapped[str] = mapped_column(String(64))
    province_code: Mapped[str] = mapped_column(String(16))
    hour_bj: Mapped[datetime] = mapped_column(DateTime)
    nature: Mapped[str] = mapped_column(String(32), default="observation")  # observation|prediction
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    baseline: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_status: Mapped[str] = mapped_column(String(32), default="ok")
    rule_version: Mapped[str] = mapped_column(String(64))
    group_key: Mapped[str] = mapped_column(String(128), index=True)
    explanation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hazard_context: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    data_version: Mapped[str] = mapped_column(String(64), default="v1", server_default="v1")
    dims_key: Mapped[Optional[str]] = mapped_column(String(96), nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    requires_future_window: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    evidences = relationship("AnomalyEvidence", back_populates="anomaly")
    suggestions = relationship("Suggestion", back_populates="anomaly")

    __table_args__ = (
        Index("ix_anomaly_filter", "dataset_id", "event_id", "analysis_scope", "hour_bj"),
    )


class AnomalyEvidence(Base):
    __tablename__ = "anomaly_evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    anomaly_id: Mapped[int] = mapped_column(Integer, ForeignKey("anomaly.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(64))
    ref_table: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ref_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    anomaly = relationship("Anomaly", back_populates="evidences")


class Suggestion(Base):
    __tablename__ = "suggestion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"))
    anomaly_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("anomaly.id"), nullable=True)
    suggestion_code: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    trigger_reason: Mapped[str] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(32), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    data_version: Mapped[str] = mapped_column(String(64), default="v1", server_default="v1")

    anomaly = relationship("Anomaly", back_populates="suggestions")


class ReviewRecord(Base):
    __tablename__ = "review_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(32))
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    operator: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class AnalysisRun(Base):
    """One versioned recomputation of an event; outputs are tagged with data_version."""

    __tablename__ = "analysis_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    data_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    rule_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trigger: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ActiveVersion(Base):
    """Pointer to the data_version currently served for an event."""

    __tablename__ = "active_version"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data_version: Mapped[str] = mapped_column(String(64))
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ActionTask(Base):
    """Human-authorised business action derived from a reviewed suggestion; distinct from TaskRun."""

    __tablename__ = "action_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, index=True)
    suggestion_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text)
    owner: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    receipt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class TaskRun(Base):
    __tablename__ = "task_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    task_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("task_type", "idempotency_key", name="uq_task_idempotency"),
    )


class ForecastSnapshot(Base):
    __tablename__ = "forecast_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    source: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(DateTime)
    arrived_at: Mapped[datetime] = mapped_column(DateTime)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    raw_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    points = relationship("ForecastPoint", back_populates="snapshot")


class ForecastPoint(Base):
    __tablename__ = "forecast_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(Integer, ForeignKey("forecast_snapshot.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    valid_time: Mapped[datetime] = mapped_column(DateTime)
    lead_hours: Mapped[int] = mapped_column(Integer)
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    metric: Mapped[str] = mapped_column(String(64))
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    version: Mapped[str] = mapped_column(String(64), default="v1")
    province_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    path_distance_proxy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    snapshot = relationship("ForecastSnapshot", back_populates="points")


class IngestionCursor(Base):
    __tablename__ = "ingestion_cursor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(64))
    cursor_value: Mapped[str] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dataset_id", "event_id", "source", name="uq_ingestion_cursor"),
    )


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_key: Mapped[str] = mapped_column(String(128), unique=True)
    target_id: Mapped[str] = mapped_column(String(64))
    horizon_hours: Mapped[int] = mapped_column(Integer)
    model_kind: Mapped[str] = mapped_column(String(32))  # baseline|tree|demo
    data_mode: Mapped[str] = mapped_column(String(16))
    feature_contract: Mapped[dict[str, Any]] = mapped_column(JSON)
    train_window: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    metrics: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PredictionRun(Base):
    __tablename__ = "prediction_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    event_id: Mapped[int] = mapped_column(Integer, ForeignKey("event.id"), index=True)
    origin_time: Mapped[datetime] = mapped_column(DateTime)
    model_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    quality_status: Mapped[str] = mapped_column(String(32), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PredictionResult(Base):
    __tablename__ = "prediction_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("prediction_run.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[int] = mapped_column(Integer)
    province_code: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[str] = mapped_column(String(64))
    origin_time: Mapped[datetime] = mapped_column(DateTime)
    valid_time: Mapped[datetime] = mapped_column(DateTime)
    lead_hours: Mapped[int] = mapped_column(Integer)
    point_pred: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    interval_low: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    interval_high: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(64))
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model_version: Mapped[str] = mapped_column(String(64))
    train_cutoff: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    data_version: Mapped[str] = mapped_column(String(64), default="v1")
    quality_status: Mapped[str] = mapped_column(String(32), default="ok")

    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "event_id",
            "province_code",
            "target_id",
            "origin_time",
            "valid_time",
            "model_version",
            "run_id",
            name="uq_prediction_result",
        ),
        Index("ix_pred_query", "dataset_id", "event_id", "origin_time", "target_id"),
    )


class EvaluationResult(Base):
    __tablename__ = "evaluation_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_id: Mapped[str] = mapped_column(String(64))
    horizon_hours: Mapped[int] = mapped_column(Integer)
    split_info: Mapped[dict[str, Any]] = mapped_column(JSON)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DataReadinessReport(Base):
    __tablename__ = "data_readiness_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    report: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
