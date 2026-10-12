"""cost_entries: lines without a task, and the client that incurred them

A platform-funded tool call a Registered Client makes over /mcp is paid for like
one a run makes, but belongs to no task: ``task_id`` becomes nullable and
``client_id`` names the client. Every existing row keeps its task.

The ledger is also the usage log billing meters, read in commit order of
``occurred_at`` for the lines the platform funded; the partial index serves that
reader.

Revision ID: 20261012_1400_cost_entry_client
Revises: 20261012_1300_platform_mcp
Create Date: 2026-10-12 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261012_1400_cost_entry_client"
down_revision: str | None = "20261012_1300_platform_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("cost_entries", "task_id", existing_type=postgresql.UUID(), nullable=True)
    op.add_column(
        "cost_entries", sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index(
        "ix_cost_entries_platform_occurred",
        "cost_entries",
        ["occurred_at", "id"],
        postgresql_where=sa.text("managed_by = 'platform'"),
    )


def downgrade() -> None:
    op.drop_index("ix_cost_entries_platform_occurred", table_name="cost_entries")
    op.drop_column("cost_entries", "client_id")
    op.execute("DELETE FROM cost_entries WHERE task_id IS NULL")
    op.alter_column("cost_entries", "task_id", existing_type=postgresql.UUID(), nullable=False)
