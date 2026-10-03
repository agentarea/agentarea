"""Run feedback, evaluation suites, cases, runs and trials

``run_feedback`` holds one person's verdict on a run. ``eval_suites`` and
``eval_cases`` define offline tests that live outside any agent revision, so a
proposal cannot edit its own test. ``eval_runs`` execute a suite against a
baseline revision and optionally a candidate; each ``eval_trials`` row is one
case on one arm, run as a real task in evaluation mode.

Revision ID: 20261003_1300_eval_tables
Revises: 20261003_1200_agent_revisions
Create Date: 2026-10-03 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261003_1300_eval_tables"
down_revision: str | None = "20261003_1200_agent_revisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UUID = postgresql.UUID(as_uuid=True)


def _scoped_columns() -> list[sa.Column]:
    return [
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def _scoped_indexes(table: str) -> None:
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])
    op.create_index(f"ix_{table}_created_by", table, ["created_by"])


def upgrade() -> None:
    op.create_table(
        "run_feedback",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("task_id", _UUID, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", _UUID, nullable=False),
        sa.Column("rating", sa.String(8), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("event_id", sa.String(255), nullable=True),
        *_scoped_columns(),
        sa.UniqueConstraint("task_id", "created_by", name="uq_run_feedback_author"),
        sa.CheckConstraint("rating IN ('good', 'bad')", name="ck_run_feedback_rating"),
    )
    op.create_index("ix_run_feedback_task_id", "run_feedback", ["task_id"])
    op.create_index("ix_run_feedback_agent_id", "run_feedback", ["agent_id"])
    _scoped_indexes("run_feedback")

    op.create_table(
        "eval_suites",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        *_scoped_columns(),
    )
    _scoped_indexes("eval_suites")

    op.create_table(
        "eval_cases",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "suite_id", _UUID, sa.ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("checks", postgresql.JSONB(), nullable=False),
        sa.Column("stubs", postgresql.JSONB(), nullable=False),
        sa.Column("source_task_id", _UUID, nullable=True),
        *_scoped_columns(),
    )
    op.create_index("ix_eval_cases_suite_id", "eval_cases", ["suite_id"])
    _scoped_indexes("eval_cases")

    op.create_table(
        "eval_runs",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "suite_id", _UUID, sa.ForeignKey("eval_suites.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "agent_id", _UUID, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "baseline_revision_id",
            _UUID,
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_revision_id",
            _UUID,
            sa.ForeignKey("agent_revisions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("trials", sa.Integer(), nullable=False),
        sa.Column("concurrency", sa.Integer(), nullable=False),
        sa.Column("budget_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stop_reason", sa.String(64), nullable=True),
        sa.Column("workflow_id", sa.String(255), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *_scoped_columns(),
        sa.CheckConstraint("trials BETWEEN 1 AND 20", name="ck_eval_runs_trials"),
        sa.CheckConstraint("concurrency BETWEEN 1 AND 10", name="ck_eval_runs_concurrency"),
        sa.CheckConstraint("budget_usd > 0", name="ck_eval_runs_budget"),
    )
    op.create_index("ix_eval_runs_suite_id", "eval_runs", ["suite_id"])
    op.create_index("ix_eval_runs_agent_id", "eval_runs", ["agent_id"])
    op.create_index("ix_eval_runs_candidate_revision_id", "eval_runs", ["candidate_revision_id"])
    _scoped_indexes("eval_runs")

    op.create_table(
        "eval_trials",
        sa.Column("id", _UUID, primary_key=True),
        sa.Column(
            "run_id", _UUID, sa.ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "case_id", _UUID, sa.ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("arm", sa.String(16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("task_id", _UUID, sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("check_results", postgresql.JSONB(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 4), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *_scoped_columns(),
        sa.UniqueConstraint("run_id", "case_id", "arm", "attempt", name="uq_eval_trials_slot"),
    )
    op.create_index("ix_eval_trials_run_id", "eval_trials", ["run_id"])
    _scoped_indexes("eval_trials")


def downgrade() -> None:
    op.drop_table("eval_trials")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_table("eval_suites")
    op.drop_table("run_feedback")
