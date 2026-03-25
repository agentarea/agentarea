"""Add mcp_access_tokens table for PAT-based MCP Bearer auth

Revision ID: 007_add_mcp_access_tokens
Revises: 006_add_mcp_auth_compound_tables
Create Date: 2026-03-02 00:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "007_add_mcp_access_tokens"
down_revision: str = "006_add_mcp_auth_compound_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_access_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Human-friendly label set by the user
        sa.Column("name", sa.String(255), nullable=False),
        # SHA-256 hex digest of the raw token (raw token never stored)
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        # First 12 chars of the raw token for display identification
        sa.Column("token_prefix", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_mcp_access_tokens_workspace_id", "mcp_access_tokens", ["workspace_id"])
    op.create_index("ix_mcp_access_tokens_token_hash", "mcp_access_tokens", ["token_hash"])


def downgrade() -> None:
    op.drop_index("ix_mcp_access_tokens_token_hash", table_name="mcp_access_tokens")
    op.drop_index("ix_mcp_access_tokens_workspace_id", table_name="mcp_access_tokens")
    op.drop_table("mcp_access_tokens")
