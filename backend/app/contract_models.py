"""前端契约所需的少量元数据，不重写微博和铁路原始事实表。"""

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class Dataset(Base):
    """显式创建的科研数据集；服务启动不生成真实或演示数据。"""

    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(String(10), default="real")
    __table_args__ = (CheckConstraint("data_mode = 'real'"),)


class ResearchEvent(Base):
    """数字事件 ID 映射官方台风编号；MVP 一个台风只注册一次，避免重复归属。"""

    __tablename__ = "research_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    typhoon_id: Mapped[str] = mapped_column(ForeignKey("typhoons.id"), unique=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (CheckConstraint("end_time >= start_time"),)


class ImportTicket(Base):
    """随机预检凭证绑定文件、事件及数据类别；对外批次 ID 为数字。"""

    __tablename__ = "import_tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("research_events.id"), index=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), unique=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
