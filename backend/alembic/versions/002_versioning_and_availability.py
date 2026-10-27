"""versioned analysis runs, availability timestamps, review operator, action tasks

Revision ID: 002
Revises: 001
Create Date: 2026-10-26

Additive only: existing rows are kept. Columns and tables are created only when
absent, because revision 001 builds the schema from current metadata on fresh
databases while older databases were created before these fields existed.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COLUMNS: list[tuple[str, sa.Column]] = [
    ("weibo_raw", sa.Column("ingested_at", sa.DateTime(), nullable=True)),
    ("weibo_clean", sa.Column("available_at", sa.DateTime(), nullable=True)),
    ("train_stop", sa.Column("valid_from", sa.DateTime(), nullable=True)),
    ("train_stop", sa.Column("valid_to", sa.DateTime(), nullable=True)),
    ("suspension_region_hour", sa.Column("run_key", sa.String(96), nullable=True)),
    ("suspension_region_hour", sa.Column("stations", sa.JSON(), nullable=True)),
    ("suspension_region_hour", sa.Column("available_at", sa.DateTime(), nullable=True)),
    ("province_hour_metric", sa.Column("available_at", sa.DateTime(), nullable=True)),
    ("province_hour_metric", sa.Column("computed_at", sa.DateTime(), nullable=True)),
    ("anomaly", sa.Column("data_version", sa.String(64), nullable=False, server_default="v1")),
    ("anomaly", sa.Column("dims_key", sa.String(96), nullable=True)),
    ("anomaly", sa.Column("available_at", sa.DateTime(), nullable=True)),
    ("anomaly", sa.Column("decided_at", sa.DateTime(), nullable=True)),
    ("anomaly", sa.Column("requires_future_window", sa.Boolean(), nullable=False, server_default="0")),
    ("suggestion", sa.Column("data_version", sa.String(64), nullable=False, server_default="v1")),
    ("review_record", sa.Column("operator", sa.String(64), nullable=True)),
    ("forecast_point", sa.Column("province_code", sa.String(16), nullable=True)),
    ("forecast_point", sa.Column("path_distance_proxy", sa.Float(), nullable=True)),
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

    if "analysis_run" not in tables:
        op.create_table(
            "analysis_run",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), index=True),
            sa.Column("data_version", sa.String(64), nullable=True),
            sa.Column("status", sa.String(32)),
            sa.Column("rule_version", sa.String(64), nullable=True),
            sa.Column("trigger", sa.String(64), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("report", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
        )
    if "active_version" not in tables:
        op.create_table(
            "active_version",
            sa.Column("dataset_id", sa.String(64), primary_key=True),
            sa.Column("event_id", sa.Integer(), primary_key=True),
            sa.Column("data_version", sa.String(64)),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )
    if "action_task" not in tables:
        op.create_table(
            "action_task",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("dataset_id", sa.String(64), index=True),
            sa.Column("event_id", sa.Integer(), index=True),
            sa.Column("suggestion_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.Text()),
            sa.Column("owner", sa.String(64), nullable=True),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(32)),
            sa.Column("receipt", sa.Text(), nullable=True),
            sa.Column("review_note", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )

    # Pre-existing outputs were produced without versions; serve them as "v1" until a rerun.
    bind.execute(
        sa.text(
            "INSERT INTO active_version (dataset_id, event_id, data_version) "
            "SELECT DISTINCT a.dataset_id, a.event_id, 'v1' FROM province_hour_metric a "
            "WHERE NOT EXISTS (SELECT 1 FROM active_version v "
            "WHERE v.dataset_id = a.dataset_id AND v.event_id = a.event_id)"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for name in ("action_task", "active_version", "analysis_run"):
        if name in tables:
            op.drop_table(name)
    for table, column in reversed(NEW_COLUMNS):
        if table in tables and column.name in _columns(inspector, table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column.name)
