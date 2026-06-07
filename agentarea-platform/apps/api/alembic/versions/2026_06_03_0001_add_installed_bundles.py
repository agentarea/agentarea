"""add installed_bundles

Provenance + idempotency record for installed agent packages. Stores the
fully-normalized canonical package (jsonb) keyed by name within a workspace.

Revision ID: 20260603_installed_bundles
Revises: 011_mcp_instance_spec_not_null
Create Date: 2026-06-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260603_installed_bundles"
down_revision: str | None = "011_mcp_instance_spec_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "installed_bundles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="installed"),
        sa.Column("canonical", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("install_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_installed_bundles_workspace_id",
        "installed_bundles",
        ["workspace_id"],
    )
    op.create_index(
        "ix_installed_bundles_created_by",
        "installed_bundles",
        ["created_by"],
    )
    op.create_index(
        "ix_installed_bundles_workspace_name",
        "installed_bundles",
        ["workspace_id", "name"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_installed_bundles_workspace_name",
        table_name="installed_bundles",
    )
    op.drop_index(
        "ix_installed_bundles_created_by",
        table_name="installed_bundles",
    )
    op.drop_index(
        "ix_installed_bundles_workspace_id",
        table_name="installed_bundles",
    )
    op.drop_table("installed_bundles")
