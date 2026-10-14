"""Spend lines say whether they are final, and connections carry a member-set cost

A ``cost_entries`` line is an estimate until billing captures what it held, the
vendor settles what a run cost, or billing converts a foreign currency; the
superseding line is final. Lines still waiting are found by their
``evidence->>'settle'`` mark through a partial index, so no work-queue table is
needed (wiki ADR-0038 rev. 2, §2.7).

A connection the workspace pays for can carry its own cost declaration, set by a
member, which wins over its connector's (§2.3).

Revision ID: 20261014_1200_cost_not_price
Revises: 20261013_2200_drop_decide
Create Date: 2026-10-14 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_1200_cost_not_price"
down_revision: str | None = "20261013_2200_drop_decide"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cost_entries",
        sa.Column("estimate", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_cost_entries_unsettled",
        "cost_entries",
        ["occurred_at"],
        postgresql_where=sa.text("evidence ? 'settle'"),
    )
    op.add_column("openapi_connections", sa.Column("cost", postgresql.JSONB(), nullable=True))
    op.add_column("mcp_server_instances", sa.Column("cost", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_server_instances", "cost")
    op.drop_column("openapi_connections", "cost")
    op.drop_index("ix_cost_entries_unsettled", table_name="cost_entries")
    op.drop_column("cost_entries", "estimate")
