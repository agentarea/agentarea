"""task_conversation_entries: the model conversation of a task, out of the engine

The conversation used to travel inside Temporal: in every model-call payload and
in the workflow's continue-as-new input, capped at 2 MiB. It now lives here,
one row per entry at a position the workflow assigns, and activities read the
window the model sees.

Revision ID: 20260930_1000_task_conversation
Revises: 20260929_1400_item_in_source
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260930_1000_task_conversation"
down_revision: str | None = "20260929_1400_item_in_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_conversation_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("tool_call_id", sa.String(255), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("task_id", "seq", name="uq_task_conversation_entries_seq"),
    )
    op.create_index(
        "ix_task_conversation_entries_workspace_id", "task_conversation_entries", ["workspace_id"]
    )
    op.create_index(
        "ix_task_conversation_entries_created_by", "task_conversation_entries", ["created_by"]
    )


def downgrade() -> None:
    op.drop_table("task_conversation_entries")
