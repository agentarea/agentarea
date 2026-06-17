"""Drop task_policy_snapshots table.

The per-task effective governance policy is no longer persisted. It is served
on demand by querying the task's Temporal workflow, where the resolved
effective policy already lives in workflow state. This migration removes the
now-unused ``task_policy_snapshots`` table.

Revision ID: 20260616_1200_drop_tps
Revises: 20260615_1200_reg_item_name_idx
Create Date: 2026-06-16 12:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "20260616_1200_drop_tps"
down_revision = "20260615_1200_reg_item_name_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_task_policy_snapshots_task_id", table_name="task_policy_snapshots")
    op.drop_index("ix_task_policy_snapshots_created_by", table_name="task_policy_snapshots")
    op.drop_index("ix_task_policy_snapshots_workspace_id", table_name="task_policy_snapshots")
    op.drop_table("task_policy_snapshots")


def downgrade() -> None:
    op.create_table(
        "task_policy_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("effective_policy", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_policy_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolver_version", sa.String(100), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "workspace_id",
            "task_id",
            name="uq_task_policy_snapshots_task",
        ),
    )
    op.create_index(
        "ix_task_policy_snapshots_workspace_id", "task_policy_snapshots", ["workspace_id"]
    )
    op.create_index("ix_task_policy_snapshots_created_by", "task_policy_snapshots", ["created_by"])
    op.create_index("ix_task_policy_snapshots_task_id", "task_policy_snapshots", ["task_id"])
