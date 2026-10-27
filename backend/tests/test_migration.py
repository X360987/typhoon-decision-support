"""Revision 002 on a database created before it: existing rows survive upgrade, downgrade and re-upgrade."""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]


def _cfg(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.attributes["database_url"] = url
    cfg.attributes["skip_logging_config"] = True
    return cfg


def _old_database(url: str) -> None:
    eng = sa.create_engine(url)
    with eng.begin() as c:
        c.exec_driver_sql(
            "CREATE TABLE province_hour_metric (id INTEGER PRIMARY KEY, dataset_id VARCHAR(64), event_id INTEGER, "
            "province_code VARCHAR(16), hour_bj DATETIME, metric_id VARCHAR(64), value FLOAT, version VARCHAR(32))"
        )
        c.exec_driver_sql(
            "CREATE TABLE anomaly (id INTEGER PRIMARY KEY, dataset_id VARCHAR(64), event_id INTEGER, anomaly_type VARCHAR(64))"
        )
        c.exec_driver_sql(
            "CREATE TABLE review_record (id INTEGER PRIMARY KEY, target_type VARCHAR(32), target_id INTEGER, action VARCHAR(32), note TEXT)"
        )
        c.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
        c.exec_driver_sql("INSERT INTO alembic_version VALUES ('001')")
        c.exec_driver_sql(
            "INSERT INTO province_hour_metric VALUES (1, 'legacy', 7, 'FJ', '2023-07-27 10:00:00', 'negative_ratio', 0.4, 'v1')"
        )
        c.exec_driver_sql("INSERT INTO anomaly VALUES (1, 'legacy', 7, 'negative_ratio_spike')")
        c.exec_driver_sql("INSERT INTO review_record VALUES (1, 'anomaly', 1, 'approve', '旧核验')")
    eng.dispose()


def test_revision_002_keeps_existing_rows(tmp_path):
    url = f"sqlite:///{(tmp_path / 'old.db').as_posix()}"
    _old_database(url)
    cfg = _cfg(url)

    command.upgrade(cfg, "head")
    eng = sa.create_engine(url)
    insp = sa.inspect(eng)
    assert {"analysis_run", "active_version", "action_task"} <= set(insp.get_table_names())
    assert {"data_version", "available_at", "requires_future_window"} <= {c["name"] for c in insp.get_columns("anomaly")}
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT anomaly_type, data_version FROM anomaly").all() == [("negative_ratio_spike", "v1")]
        assert c.exec_driver_sql("SELECT note FROM review_record").scalar() == "旧核验"
        assert c.exec_driver_sql("SELECT dataset_id, event_id, data_version FROM active_version").all() == [("legacy", 7, "v1")]
        assert c.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == "002"
    eng.dispose()

    command.downgrade(cfg, "001")
    eng = sa.create_engine(url)
    insp = sa.inspect(eng)
    assert "analysis_run" not in insp.get_table_names()
    assert "data_version" not in {c["name"] for c in insp.get_columns("anomaly")}
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM anomaly").scalar() == 1
        assert c.exec_driver_sql("SELECT count(*) FROM province_hour_metric").scalar() == 1
    eng.dispose()

    command.upgrade(cfg, "head")
    eng = sa.create_engine(url)
    with eng.connect() as c:
        assert c.exec_driver_sql("SELECT count(*) FROM anomaly").scalar() == 1
        assert c.exec_driver_sql("SELECT note FROM review_record").scalar() == "旧核验"
    eng.dispose()
