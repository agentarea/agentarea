"""add artifact events

Revision ID: ss1_add_artifact_events
Revises: rr1_drop_workspace_settings
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "ss1_add_artifact_events"
down_revision: str | None = "rr1_drop_workspace_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "artifact_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("actor_type", sa.String(20), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=True),
        sa.Column("task_id", sa.String(255), nullable=True),
    )
    op.create_index("ix_artifact_events_workspace_id", "artifact_events", ["workspace_id"])
    op.create_index("ix_artifact_events_created_by", "artifact_events", ["created_by"])
    op.create_index("ix_artifact_events_path", "artifact_events", ["path"])


def downgrade() -> None:
    op.drop_index("ix_artifact_events_path", table_name="artifact_events")
    op.drop_index("ix_artifact_events_created_by", table_name="artifact_events")
    op.drop_index("ix_artifact_events_workspace_id", table_name="artifact_events")
    op.drop_table("artifact_events")
