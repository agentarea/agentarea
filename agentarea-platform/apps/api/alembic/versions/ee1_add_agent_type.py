"""add agent_type to agents

Revision ID: ee1_add_agent_type
Revises: bb2fc6b67389
Create Date: 2026-03-19 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ee1_add_agent_type"
down_revision: str | None = "bb2fc6b67389"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("agent_type", sa.String(), nullable=False, server_default="stateless"),
    )


def downgrade() -> None:
    op.drop_column("agents", "agent_type")
