"""cost_entries carry the chain their spend belongs to: correlation_id, causation_id

A task's lines take its task's ids; a task started with no entry event (the
API, A2A, a schedule) is its own chain's start. No customers: existing rows are
not backfilled.

Revision ID: 20261015_1800_cost_entries_chain
Revises: 20261015_1700_task_log
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_1800_cost_entries_chain"
down_revision: str | None = "20261015_1700_task_log"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cost_entries", sa.Column("correlation_id", sa.String(255), nullable=True))
    op.add_column("cost_entries", sa.Column("causation_id", sa.String(255), nullable=True))
    op.create_index("ix_cost_entries_correlation_id", "cost_entries", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_cost_entries_correlation_id", table_name="cost_entries")
    op.drop_column("cost_entries", "causation_id")
    op.drop_column("cost_entries", "correlation_id")
