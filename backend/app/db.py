"""数据库会话生命周期；建表由 Alembic 迁移完成。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    """每个请求使用独立会话，异常离开时回滚未提交事务。"""
    with SessionLocal() as session:
        yield session
