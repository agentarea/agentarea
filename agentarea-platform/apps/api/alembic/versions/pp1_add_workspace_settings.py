"""add workspace_settings

Per-workspace configuration row keyed by workspace_id. Holds the monthly
budget cap (nullable = no enforcement) and is the home for future workspace
config (timezone, retention) without retrofitting a full Workspace entity.

Revision ID: pp1_add_workspace_settings
Revises: 011_mcp_instance_spec_not_null
Create Date: 2026-05-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "pp1_add_workspace_settings"
down_revision: str | None = "011_mcp_instance_spec_not_null"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspace_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("monthly_cap_usd", sa.Numeric(12, 2), nullable=True),
        sa.UniqueConstraint("workspace_id", name="uq_workspace_settings_workspace_id"),
    )
    op.create_index(
        "ix_workspace_settings_workspace_id",
        "workspace_settings",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workspace_settings_workspace_id", table_name="workspace_settings")
    op.drop_table("workspace_settings")
