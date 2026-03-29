"""Add a2ui_enabled column to agents table

Revision ID: 010_add_a2ui_enabled
Revises: 009_merge_heads
Create Date: 2026-03-24 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010_add_a2ui_enabled"
down_revision: str = "009_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("a2ui_enabled", sa.Boolean(), nullable=True, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("agents", "a2ui_enabled")
