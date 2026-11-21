"""核心关系模型。平台 ID 使用字符串，历史身份不随账号资料更新。"""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有业务表的声明式基类。"""


class Typhoon(Base):
    """经核对的官方台风目录；不向普通 HTTP 客户端开放新增接口。"""

    __tablename__ = "typhoons"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str] = mapped_column(Text)


class ImportBatch(Base):
    """一次上传的原文件、预览与最终结果；提交操作可重复调用。"""

    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    typhoon_id: Mapped[str | None] = mapped_column(ForeignKey("typhoons.id"))
    catalog_year: Mapped[int | None] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="previewed")
    rows: Mapped[list] = mapped_column(JSON)
    report: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Account(Base):
    """账号当前资料；政府映射未确定时 is_government 保持未知。"""

    __tablename__ = "accounts"
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    nickname: Mapped[str | None] = mapped_column(Text)
    verified_type: Mapped[str | None] = mapped_column(String(64))
    is_authoritative: Mapped[bool | None] = mapped_column(Boolean)
    is_government: Mapped[bool | None] = mapped_column(Boolean)
    profile: Mapped[dict] = mapped_column(JSON, default=dict)


class Weibo(Base):
    """微博正文及一次互动采集值；原始模板信息一并保留。"""

    __tablename__ = "weibo"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("accounts.user_id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    reposts: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    heat: Mapped[int | None] = mapped_column(Integer)
    ip_region: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = tuple(
        CheckConstraint(f"{k} >= 0", name=f"ck_weibo_{k}")
        for k in ("reposts", "comments", "likes", "heat")
    )


class EventPost(Base):
    """事件与微博的关系及该次采集身份快照，阶段属于事件语境。"""

    __tablename__ = "event_posts"
    typhoon_id: Mapped[str] = mapped_column(ForeignKey("typhoons.id"), primary_key=True)
    weibo_id: Mapped[str] = mapped_column(ForeignKey("weibo.id"), primary_key=True)
    stage: Mapped[str | None] = mapped_column(String(10))
    verified_type: Mapped[str | None] = mapped_column(String(64))
    is_authoritative: Mapped[bool | None] = mapped_column(Boolean)
    is_government: Mapped[bool | None] = mapped_column(Boolean)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    __table_args__ = (CheckConstraint("stage IN ('灾前','灾中','灾后')", name="ck_stage"),)


class Train(Base):
    """年度车次目录；原始 ID 在不同年份不具有全局唯一性。"""

    __tablename__ = "trains"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer)
    source_train_id: Mapped[str] = mapped_column(String(64))
    train_no: Mapped[str] = mapped_column(String(32))
    __table_args__ = (
        UniqueConstraint("year", "source_train_id"),
        UniqueConstraint("year", "train_no"),
        UniqueConstraint("id", "year"),
    )


class Station(Base):
    """标准车站和可选 WGS84 坐标；无坐标时不制造地图点位。"""

    __tablename__ = "stations"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    longitude: Mapped[float | None] = mapped_column(Float)
    latitude: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint("longitude BETWEEN -180 AND 180"),
        CheckConstraint("latitude BETWEEN -90 AND 90"),
    )


class Suspension(Base):
    """全程停运事实，业务唯一键不包含来源，禁止静默覆盖冲突。"""

    __tablename__ = "suspensions"
    record_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    typhoon_id: Mapped[str] = mapped_column(ForeignKey("typhoons.id"), index=True)
    departure_date: Mapped[date] = mapped_column(Date, index=True)
    catalog_year: Mapped[int] = mapped_column(Integer)
    train_id: Mapped[int] = mapped_column(Integer)
    raw_train_no: Mapped[str] = mapped_column(String(100))
    origin: Mapped[str | None] = mapped_column(String(100))
    destination: Mapped[str | None] = mapped_column(String(100))
    scope: Mapped[str] = mapped_column(String(20), default="全程停运")
    source_weibo_id: Mapped[str] = mapped_column(ForeignKey("weibo.id"))
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    source_row: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (
        UniqueConstraint("typhoon_id", "departure_date", "train_id"),
        ForeignKeyConstraint(["train_id", "catalog_year"], ["trains.id", "trains.year"]),
        CheckConstraint("scope = '全程停运'"),
        CheckConstraint("EXTRACT(YEAR FROM departure_date) = catalog_year"),
    )


class ManualSuspension(Base):
    """人工长表的一行。保留复合车次的原写法和工作簿行号。"""

    __tablename__ = "manual_suspensions"
    record_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    typhoon_id: Mapped[str] = mapped_column(ForeignKey("typhoons.id"))
    departure_date: Mapped[date] = mapped_column(Date)
    raw_train_no: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    source_row: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("typhoon_id", "departure_date", "raw_train_no"),)
    # 人工表没有站名和来源微博。查询经 app.geo.endpoints 读取，缺站名时地图计为未定位。
    origin = destination = scope = source_weibo_id = None


class Audit(Base):
    """每次覆盖保留前后值和来源批次，支持科研追溯。"""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity: Mapped[str] = mapped_column(String(30))
    entity_id: Mapped[str] = mapped_column(String(100))
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"))
    before: Mapped[dict[str, Any]] = mapped_column(JSON)
    after: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
