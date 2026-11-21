"""${message}。数据库结构版本固定，不随未来模型文件隐式改变。"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade():
    """应用当前版本。"""
    ${upgrades if upgrades else "pass"}


def downgrade():
    """回退当前版本；生产数据回退前须备份。"""
    ${downgrades if downgrades else "pass"}
