"""event source fields and pre-disaster collection tables

Revision ID: 003
Revises: 002
Create Date: 2026-11-02

Additive. Fresh databases already receive these objects from revision 001,
which creates the current metadata. This revision fills databases that were
created before the columns and tables existed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COLUMNS: list[tuple[str, sa.Column]] = [
    ("event", sa.Column("english_name", sa.String(128), nullable=True)),
    ("event", sa.Column("aliases", sa.JSON(), nullable=True)),
    ("event", sa.Column("warning_level", sa.String(32), nullable=True)),
    ("event", sa.Column("forecast_provinces", sa.JSON(), nullable=True)),
    ("event", sa.Column("source_mode", sa.String(16), nullable=True)),
]


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column in NEW_COLUMNS:
        if table in tables and column.name not in _columns(inspector, table):
            op.add_column(table, column)
    if "event" in tables:
        end = next(c for c in inspector.get_columns("event") if c["name"] == "end_time")
        if not end.get("nullable", True):
            with op.batch_alter_table("event") as batch:
                batch.alter_column("end_time", existing_type=sa.DateTime(), nullable=True)

    if "source_snapshot" not in tables:
        op.create_table(
            "source_snapshot",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), nullable=True),
            sa.Column("source_type", sa.String(32)),
            sa.Column("url", sa.Text(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime()),
            sa.Column("content_hash", sa.String(64)),
            sa.Column("body", sa.Text(), nullable=True),
        )
    if "warning_record" not in tables:
        op.create_table(
            "warning_record",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), index=True),
            sa.Column("warning_id", sa.String(64)),
            sa.Column("level", sa.String(32), nullable=True),
            sa.Column("title", sa.String(256), nullable=True),
            sa.Column("issued_at", sa.DateTime(), nullable=True),
            sa.Column("arrived_at", sa.DateTime(), nullable=True),
            sa.Column("areas", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(32)),
            sa.UniqueConstraint("dataset_id", "warning_id", name="uq_warning_dataset"),
        )
    if "keyword_set" not in tables:
        op.create_table(
            "keyword_set",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), index=True),
            sa.Column("version", sa.Integer()),
            sa.Column("keywords", sa.JSON()),
            sa.Column("negative_keywords", sa.JSON()),
            sa.Column("coverage", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.UniqueConstraint("dataset_id", "event_id", "version", name="uq_keyword_version"),
        )
    if "collection_task" not in tables:
        op.create_table(
            "collection_task",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), index=True),
            sa.Column("keyword_version", sa.Integer()),
            sa.Column("status", sa.String(32)),
            sa.Column("window_start", sa.DateTime(), nullable=True),
            sa.Column("window_end", sa.DateTime(), nullable=True),
            sa.Column("query_text", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name in ("collection_task", "keyword_set", "warning_record", "source_snapshot"):
        if name in tables:
            op.drop_table(name)
    if "event" in tables:
        present = _columns(inspector, "event")
        for column in ("source_mode", "forecast_provinces", "warning_level", "aliases", "english_name"):
            if column in present:
                op.drop_column("event", column)
