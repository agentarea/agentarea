"""A harness client is given tasks through an agent of its own

A task always runs as an agent. A task given to a Codex or Claude Code client
itself, with no agent configured, runs as the one agent that stands for the
client: ``agents.harness_client_id`` names that client. It has no instructions
of its own and is left out of the workspace's agents.

Revision ID: 20261109_1900_harness_agent
Revises: 20261107_1200_client_runner
Create Date: 2026-11-09 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261109_1900_harness_agent"
down_revision: str | None = "20261107_1200_client_runner"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "harness_client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_agents_harness_client_id", "agents", ["harness_client_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_agents_harness_client_id", table_name="agents")
    op.drop_column("agents", "harness_client_id")
