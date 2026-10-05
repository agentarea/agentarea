"""tasks: origin, correlation and causation, parent task; triggers.needs_new_owner_at

Existing rows are backfilled from what they already record: a trigger run keeps
its trigger id in parameters, a delegated task its parent in task_metadata.

Revision ID: 20261006_0910_task_provenance
Revises: 20261006_0900_event_streams
Create Date: 2026-10-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0910_task_provenance"
down_revision: str | None = "20261006_0900_event_streams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("origin_type", sa.String(32), nullable=True))
    op.add_column("tasks", sa.Column("origin_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("correlation_id", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("causation_id", sa.String(255), nullable=True))
    op.add_column(
        "tasks", sa.Column("parent_task_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_tasks_origin", "tasks", ["origin_type", "origin_id"])
    op.create_index("ix_tasks_causation_id", "tasks", ["causation_id"])
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])
    op.execute(
        """
        UPDATE tasks SET origin_type = 'trigger', origin_id = parameters::jsonb ->> 'trigger_id'
        WHERE parameters IS NOT NULL AND parameters::jsonb ? 'trigger_id'
        """
    )
    op.execute(
        """
        UPDATE tasks
        SET origin_type = 'agent',
            origin_id = task_metadata::jsonb ->> 'parent_task_id',
            causation_id = task_metadata::jsonb ->> 'parent_task_id',
            parent_task_id = (task_metadata::jsonb ->> 'parent_task_id')::uuid
        WHERE task_metadata IS NOT NULL
          AND task_metadata::jsonb ->> 'parent_task_id' ~*
              '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        """
    )
    op.add_column("triggers", sa.Column("needs_new_owner_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("triggers", "needs_new_owner_at")
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_index("ix_tasks_causation_id", table_name="tasks")
    op.drop_index("ix_tasks_origin", table_name="tasks")
    for column in ("parent_task_id", "causation_id", "correlation_id", "origin_id", "origin_type"):
        op.drop_column("tasks", column)
