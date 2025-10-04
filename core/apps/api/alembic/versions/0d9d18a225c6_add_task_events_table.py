"""add_task_events_table

Revision ID: 0d9d18a225c6
Revises: 001_initial_schema
Create Date: 2025-08-06 01:11:15.625087

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0d9d18a225c6"
down_revision: str | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create task_events table for event sourcing."""
    # ========================================
    # TASK_EVENTS TABLE
    # ========================================
    op.create_table(
        "task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column(
            "timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("event_metadata", postgresql.JSONB, nullable=False, server_default="{}"),
        # Workspace and audit fields for consistency
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
    )

    # Create indexes for performance
    op.create_index("idx_task_events_task_id_timestamp", "task_events", ["task_id", "timestamp"])
    op.create_index("idx_task_events_event_type", "task_events", ["event_type"])
    op.create_index("idx_task_events_data_gin", "task_events", ["data"], postgresql_using="gin")
    op.create_index("idx_task_events_workspace_id", "task_events", ["workspace_id"])


def downgrade() -> None:
    """Drop task_events table and indexes."""
    op.drop_index("idx_task_events_workspace_id", table_name="task_events")
    op.drop_index("idx_task_events_data_gin", table_name="task_events")
    op.drop_index("idx_task_events_event_type", table_name="task_events")
    op.drop_index("idx_task_events_task_id_timestamp", table_name="task_events")
    op.drop_table("task_events")
