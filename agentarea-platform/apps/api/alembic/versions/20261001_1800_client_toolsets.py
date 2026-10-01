"""Clients carry platform toolsets and a per-instance tool selection

``client_platform_toolsets`` attaches platform toolsets (``agentarea/runs``, ...)
to a client by namespace, each minus the methods it leaves out, so the client's
endpoint serves them beside its MCP instances. ``client_mcp_instances`` gains
``allowed_tools``: the instance's tools the client serves, NULL for all of them.

Revision ID: 20261001_1800_client_toolsets
Revises: 20261001_1200_a2a_agent_addrs
Create Date: 2026-10-01 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261001_1800_client_toolsets"
down_revision: str | None = "20261001_1200_a2a_agent_addrs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "client_platform_toolsets",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("toolset", sa.String(128), primary_key=True),
        sa.Column("disabled_methods", sa.JSON(), nullable=True),
    )
    op.add_column("client_mcp_instances", sa.Column("allowed_tools", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("client_mcp_instances", "allowed_tools")
    op.drop_table("client_platform_toolsets")
