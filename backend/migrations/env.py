"""Alembic 从同一配置读取连接信息，不复制密码。"""

from alembic import context
from sqlalchemy import create_engine

from app.config import settings
from app.models import Base
import app.contract_models  # noqa: F401

if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(settings.database_url).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
