"""Add openapi_connections table.

Revision ID: ee8ec6b67385
Revises: dd7ec6b67384
Create Date: 2026-03-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ee8ec6b67385"
down_revision: str = "dd7ec6b67384"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "openapi_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec_url", sa.Text(), nullable=True),
        sa.Column("spec_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column(
            "auth_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "available_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_openapi_connections_workspace_id", "openapi_connections", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_openapi_connections_workspace_id", table_name="openapi_connections")
    op.drop_table("openapi_connections")
