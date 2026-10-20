"""task_definitions: what to ask an agent, apart from when (ADR run authority)

A task definition is a saved ask: an agent, the text, its parameters. It runs on
demand, and a trigger may point at one instead of carrying its own text. A run
records the definition it came from, and the identity that started it.

Revision ID: 20261020_1800_task_definitions
Revises: 20261020_1000_skill_versions
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261020_1800_task_definitions"
down_revision: str | None = "20261020_1000_skill_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("task_definition_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_tasks_task_definition_id", "tasks", ["task_definition_id"])
    op.add_column("tasks", sa.Column("source_identity", sa.String(255), nullable=True))
    op.add_column(
        "triggers",
        sa.Column("task_definition_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_triggers_task_definition_id", "triggers", ["task_definition_id"])


def downgrade() -> None:
    op.drop_index("ix_triggers_task_definition_id", table_name="triggers")
    op.drop_column("triggers", "task_definition_id")
    op.drop_column("tasks", "source_identity")
    op.drop_index("ix_tasks_task_definition_id", table_name="tasks")
    op.drop_column("tasks", "task_definition_id")
    op.drop_table("task_definitions")
