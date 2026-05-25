"""drop workspace_settings table

`workspace_settings.monthly_cap_usd` was superseded by the governance policy
system (`governance_policies` with workspace scope). The table held no other
fields, so we drop it outright. Governance policies are the single source of
truth for workspace budget caps.

Revision ID: rr1_drop_workspace_settings
Revises: qq1_add_governance_policies
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "rr1_drop_workspace_settings"
down_revision: str | None = "qq1_add_governance_policies"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_workspace_settings_workspace_id", table_name="workspace_settings")
    op.drop_table("workspace_settings")


def downgrade() -> None:
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
