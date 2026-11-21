"""人工铁路长表，独立保留工作簿行来源。"""
import sqlalchemy as sa
from alembic import op

revision = "ca309871bd02"
down_revision = "a0c57bd74551"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_suspensions",
        sa.Column("record_id", sa.Integer(), primary_key=True),
        sa.Column("typhoon_id", sa.String(32), sa.ForeignKey("typhoons.id"), nullable=False),
        sa.Column("departure_date", sa.Date(), nullable=False),
        sa.Column("raw_train_no", sa.String(100), nullable=False),
        sa.Column("batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False),
        sa.Column("source_row", sa.Integer(), nullable=False),
        sa.UniqueConstraint("typhoon_id", "departure_date", "raw_train_no"),
    )


def downgrade():
    op.drop_table("manual_suspensions")
