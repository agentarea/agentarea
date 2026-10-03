"""Agent revisions and experiments; every run pinned to the revision it ran

``agent_revisions`` holds immutable snapshots of what an agent runs. The
``agents`` executable columns stay as the materialized copy of the revision its
``current_revision_id`` points at. ``tasks.agent_revision_id`` pins a run to
the revision it was submitted against, and ``tasks.experiment_id`` marks runs
an experiment assigned. ``agent_experiments`` splits traffic between the
serving revision and one candidate; at most one runs per agent.

Revision ID: 20261003_1200_agent_revisions
Revises: 20261003_1100_merge_heads
Create Date: 2026-10-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_1200_agent_revisions"
down_revision: str | None = "20261003_1100_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("parent_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("spec", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column(
            "evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("agent_id", "number", name="uq_agent_revisions_number"),
    )
    op.create_index("ix_agent_revisions_agent_id", "agent_revisions", ["agent_id"])
    op.create_index("ix_agent_revisions_workspace_id", "agent_revisions", ["workspace_id"])
    op.create_index("ix_agent_revisions_created_by", "agent_revisions", ["created_by"])

    op.add_column(
        "agents", sa.Column("current_revision_id", postgresql.UUID(as_uuid=True), nullable=True)
    )

    op.create_table(
        "agent_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "control_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("weights", postgresql.JSONB(), nullable=False),
        sa.Column("policy", postgresql.JSONB(), nullable=False),
        sa.Column(
            "decisions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_agent_experiments_agent_id", "agent_experiments", ["agent_id"])
    op.create_index("ix_agent_experiments_workspace_id", "agent_experiments", ["workspace_id"])
    op.create_index("ix_agent_experiments_created_by", "agent_experiments", ["created_by"])
    op.create_index(
        "uq_agent_experiments_running",
        "agent_experiments",
        ["agent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )

    op.add_column(
        "tasks",
        sa.Column(
            "agent_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_revisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_experiments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_agent_revision_id", "tasks", ["agent_revision_id"])
    op.create_index("ix_tasks_experiment_id", "tasks", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_experiment_id", table_name="tasks")
    op.drop_index("ix_tasks_agent_revision_id", table_name="tasks")
    op.drop_column("tasks", "experiment_id")
    op.drop_column("tasks", "agent_revision_id")
    op.drop_table("agent_experiments")
    op.drop_column("agents", "current_revision_id")
    op.drop_table("agent_revisions")
