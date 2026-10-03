"""Tables of the evals module: run feedback, suites, cases, runs and trials."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

_JSONB = JSON().with_variant(JSONB(), "postgresql")

RATING_GOOD = "good"
RATING_BAD = "bad"
RATINGS = (RATING_GOOD, RATING_BAD)

ARM_BASELINE = "baseline"
ARM_CANDIDATE = "candidate"

RUN_QUEUED = "queued"
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_STOPPED = "stopped"
RUN_FAILED = "failed"

TRIAL_PENDING = "pending"
TRIAL_RUNNING = "running"
TRIAL_DONE = "done"
TRIAL_ERROR = "error"
TRIAL_SKIPPED = "skipped"


class RunFeedback(BaseModel, WorkspaceScopedMixin):
    """A person's verdict on one run. One per person per run; rating again replaces it."""

    __tablename__ = "run_feedback"
    __table_args__ = (UniqueConstraint("task_id", "created_by", name="uq_run_feedback_author"),)

    task_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, index=True)
    rating: Mapped[str] = mapped_column(String(8), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


class EvalSuite(BaseModel, WorkspaceScopedMixin):
    """A named set of cases. Outside any agent revision: a proposal cannot edit its own test."""

    __tablename__ = "eval_suites"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvalCase(BaseModel, WorkspaceScopedMixin):
    """An input, the checks its outcome must pass, and stubs for effectful tools."""

    __tablename__ = "eval_cases"

    suite_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    input: Mapped[str] = mapped_column(Text, nullable=False)
    # Task parameters for the trial (attachments included); never run overrides.
    parameters: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False, default=dict)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(_JSONB, nullable=False, default=list)
    stubs: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False, default=dict)
    source_task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class EvalRun(BaseModel, WorkspaceScopedMixin):
    """A suite run against a baseline revision and, optionally, a candidate."""

    __tablename__ = "eval_runs"

    suite_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_suites.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    baseline_revision_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agent_revisions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_revision_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("agent_revisions.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    trials: Mapped[int] = mapped_column(Integer, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    budget_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal(0))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[dict[str, Any]] = mapped_column(_JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalTrial(BaseModel, WorkspaceScopedMixin):
    """One execution of one case on one arm; a real task run in evaluation mode."""

    __tablename__ = "eval_trials"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", "arm", "attempt", name="uq_eval_trials_slot"),
    )

    run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("eval_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    case_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("eval_cases.id", ondelete="CASCADE"), nullable=False
    )
    arm: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    check_results: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSONB, nullable=False, default=list
    )
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal(0))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# The per-run rollup view (alembic owns it). A separate MetaData keeps it out
# of create_all.
task_summary = Table(
    "task_summary",
    MetaData(),
    Column("task_id", PG_UUID(as_uuid=True)),
    Column("cost_usd", Numeric),
    Column("duration_ms", Numeric),
    Column("iterations", Integer),
    Column("tools_called", Integer),
    Column("tools_failed", Integer),
    Column("final_response", Text),
    Column("last_error", Text),
)
