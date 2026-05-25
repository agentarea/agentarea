"""add governance policies

Revision ID: qq1_add_governance_policies
Revises: pp1_add_workspace_settings
Create Date: 2026-05-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "qq1_add_governance_policies"
down_revision: str | None = "pp1_add_workspace_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "governance_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False),
        sa.Column("scope_id", sa.String(255), nullable=False),
        sa.Column("document", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint(
            "workspace_id",
            "scope_type",
            "scope_id",
            name="uq_governance_policies_scope",
        ),
    )
    op.create_index("ix_governance_policies_workspace_id", "governance_policies", ["workspace_id"])
    op.create_index("ix_governance_policies_created_by", "governance_policies", ["created_by"])
    op.create_index("ix_governance_policies_scope_type", "governance_policies", ["scope_type"])
    op.create_index("ix_governance_policies_scope_id", "governance_policies", ["scope_id"])

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


def downgrade() -> None:
    op.drop_index("ix_task_policy_snapshots_task_id", table_name="task_policy_snapshots")
    op.drop_index("ix_task_policy_snapshots_created_by", table_name="task_policy_snapshots")
    op.drop_index("ix_task_policy_snapshots_workspace_id", table_name="task_policy_snapshots")
    op.drop_table("task_policy_snapshots")
    op.drop_index("ix_governance_policies_scope_id", table_name="governance_policies")
    op.drop_index("ix_governance_policies_scope_type", table_name="governance_policies")
    op.drop_index("ix_governance_policies_created_by", table_name="governance_policies")
    op.drop_index("ix_governance_policies_workspace_id", table_name="governance_policies")
    op.drop_table("governance_policies")
