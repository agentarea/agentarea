"""Add tasks.scheduled_at — one-shot runs deferred to an absolute time

A task with ``scheduled_at`` set is dispatched to Temporal immediately but with a
start delay, and sits in status 'scheduled' until its moment arrives. NULL means
"run now", which is every task that existed before this migration.

Timezone-aware on purpose: ``started_at`` and ``completed_at`` are naive
timestamps, but those record instants that already happened in server time,
whereas a future run time without an offset would fire at the wrong moment.

Revision ID: 20260831_1200_task_sched_at
Revises: 20260828_1000_drop_ws_type
Create Date: 2026-08-31 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_1200_task_sched_at"
down_revision: str | None = "20260828_1000_drop_ws_type"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Partial: only pending runs are ever queried by due time, and they are a
    # rounding error next to the full task history.
    op.create_index(
        "ix_tasks_due",
        "tasks",
        ["workspace_id", "scheduled_at"],
        postgresql_where=sa.text("status = 'scheduled'"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_due", table_name="tasks")
    op.drop_column("tasks", "scheduled_at")
