"""Every test run uses a throwaway SQLite file; the developer database is never touched."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="typhoon-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{(_TMP / 'test.db').as_posix()}",
        "DATA_MODE": "demo",
        "API_KEY": "",
        "PRECHECK_SECRET": "test-precheck-secret",
        "ARTIFACT_DIR": str(_TMP / "artifacts"),
        "MAX_UPLOAD_MB": "20",
    }
)

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(scope="session")
def seeded():
    from app.db import SessionLocal
    from app.services.demo_setup import seed_and_prepare_demo
    from scripts.init_db import upgrade_schema

    upgrade_schema()
    db = SessionLocal()
    try:
        out = seed_and_prepare_demo(db)
    finally:
        db.close()
    assert out["seed"]["status"] == "ok"
    return out


@pytest.fixture
def db(seeded):
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def settings_env(monkeypatch):
    """Override server settings for one test (data mode, API key, upload limit)."""

    def apply(**values):
        for key, value in values.items():
            monkeypatch.setenv(key.upper(), str(value))
        get_settings.cache_clear()

    yield apply
    monkeypatch.undo()
    get_settings.cache_clear()


def pytest_sessionfinish(session, exitstatus):
    try:
        from app.db import engine

        engine.dispose()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(_TMP, ignore_errors=True)
