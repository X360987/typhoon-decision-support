"""集成测试只连接以 _test 结尾的 PostgreSQL 数据库。"""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.main import app
from app.models import Base, Typhoon


@pytest.fixture
def db(tmp_path, monkeypatch):
    url = make_url(
        os.getenv(
            "TEST_DATABASE_URL",
            str(
                make_url(settings.database_url)
                .set(database="typhoon_test")
                .render_as_string(hide_password=False)
            ),
        )
    )
    if not url.database.endswith("_test"):
        raise RuntimeError("拒绝清理非测试数据库")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        names = ",".join('"' + t.name + '"' for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    monkeypatch.setattr(settings, "storage_dir", tmp_path / "uploads")
    monkeypatch.setattr(settings, "write_api_key", "test-key")
    with Session(engine, expire_on_commit=False) as session:
        session.add(Typhoon(id="TEST", name="测试台风非真实数据", source_url="https://www.nmc.cn/"))
        session.commit()
        yield session
    engine.dispose()


@pytest.fixture
def client(db):
    def override():
        yield db

    app.dependency_overrides[get_db] = override
    with TestClient(app, headers={"X-API-Key": "test-key", "X-Operator": "pytest"}) as client:
        yield client
    app.dependency_overrides.clear()
