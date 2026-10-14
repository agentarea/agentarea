"""task_conversation_entries.attachments: images a tool returned, by reference

A tool message's images are stored with the task's offloaded context; the entry
keeps only ``[{"id", "mime_type", "size"}]`` so the model call can attach them.

Revision ID: 20261013_1500_conv_attachments
Revises: 20261013_1200_tool_cost_metering
Create Date: 2026-10-13 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261013_1500_conv_attachments"
down_revision: str | None = "20261013_1200_tool_cost_metering"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "task_conversation_entries",
        sa.Column("attachments", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_conversation_entries", "attachments")
