"""installation: the one row that identifies this installation to usage analytics

Its id is the anonymous install_id every analytics event carries; last_pulse_at is
when the daily pulse was last sent. A unique index on a constant holds the table to
a single row, so replicas creating it at once insert one.

Revision ID: 20261021_1200_installation
Revises: 20261020_1800_task_definitions
Create Date: 2026-10-21 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_1200_installation"
down_revision: str | None = "20261020_1800_task_definitions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installation",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_pulse_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_installation_single_row", "installation", [sa.text("(true)")], unique=True)


def downgrade() -> None:
    op.drop_index("uq_installation_single_row", table_name="installation")
    op.drop_table("installation")
