from collections.abc import Generator
from datetime import date, datetime
from json import dumps

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _json_dumps(obj) -> str:
    def default(o):
        if isinstance(o, (datetime, date)):
            return o.isoformat()
        raise TypeError(f"not serializable: {type(o)}")

    return dumps(obj, default=default, ensure_ascii=False)


def _make_engine():
    settings = get_settings()
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    eng = create_engine(
        url,
        pool_pre_ping=not url.startswith("sqlite"),
        pool_recycle=3600 if not url.startswith("sqlite") else -1,
        future=True,
        connect_args=connect_args,
        json_serializer=_json_dumps,
    )
    if url.startswith("sqlite"):

        @event.listens_for(eng, "connect")
        def _fk(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    elif url.startswith("mysql"):
        # System timestamps (created_at, finished_at …) are stored in UTC like SQLite's CURRENT_TIMESTAMP.
        @event.listens_for(eng, "connect")
        def _utc(dbapi_conn, _):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET time_zone = '+00:00'")
            cursor.close()

    return eng


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Reload engine after settings change (tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _make_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
