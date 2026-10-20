"""Task ORM models."""

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# Import event base model without created_at/updated_at
from .event_orm import EventBaseModel


class TaskORM(BaseModel, WorkspaceScopedMixin):  # SoftDeleteMixin commented out for now
    """Task ORM model with workspace awareness."""

    __tablename__ = "tasks"
    __table_args__ = (
        Index(
            "ix_tasks_due",
            "workspace_id",
            "scheduled_at",
            postgresql_where=text("status = 'scheduled'"),
        ),
        Index("ix_tasks_origin", "origin_type", "origin_id"),
    )

    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Timezone-aware on purpose, unlike the naive columns above: a future
    # instant that loses its offset runs at the wrong time.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_id: Mapped[str] = mapped_column(String(255), nullable=True)
    task_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=True)
    project_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    origin_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    origin_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    parent_task_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    # The causation depth of the event that started the task; 0 when none did.
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # The saved task definition this run was asked from, if any.
    task_definition_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    # Who started the run, as ``<kind>:<id>``; none for a run nothing human started.
    source_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)


class TaskEventORM(EventBaseModel, WorkspaceScopedMixin):
    """Task event ORM model for event sourcing."""

    __tablename__ = "task_events"

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})


class CostEntryORM(EventBaseModel, WorkspaceScopedMixin):
    """One paid line of spend; see ``agentarea_tasks.domain.costs``.

    A row is never updated: a later, more exact amount is a new row whose
    ``supersedes_id`` points at the one it replaces. ``currency`` is NULL only on
    rows backfilled from events stored before the ledger existed, which were
    priced in the deployment's billing currency.
    """

    __tablename__ = "cost_entries"
    __table_args__ = (
        UniqueConstraint("event_id", "category", name="uq_cost_entries_event_category"),
        Index("ix_cost_entries_workspace_occurred", "workspace_id", "occurred_at"),
        Index("ix_cost_entries_agent_occurred", "workspace_id", "agent_id", "occurred_at"),
        Index("ix_cost_entries_subject_occurred", "workspace_id", "subject_id", "occurred_at"),
    )

    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    agent_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    client_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subject_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    call_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 12), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    provider_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    payer: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vendor_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 12), nullable=True)
    vendor_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    supersedes_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    estimate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)


Index(
    "ix_cost_entries_supersedes",
    CostEntryORM.supersedes_id,
    postgresql_where=CostEntryORM.supersedes_id.isnot(None),
)
Index(
    "ix_cost_entries_platform_occurred",
    CostEntryORM.occurred_at,
    CostEntryORM.id,
    postgresql_where=CostEntryORM.payer == "platform",
)
Index(
    "ix_cost_entries_unsettled",
    CostEntryORM.occurred_at,
    postgresql_where=CostEntryORM.evidence.has_key("settle"),
)
Index(
    "ix_cost_entries_client_occurred",
    CostEntryORM.workspace_id,
    CostEntryORM.client_id,
    CostEntryORM.occurred_at,
    postgresql_where=CostEntryORM.client_id.isnot(None),
)


class TaskConversationEntryORM(EventBaseModel, WorkspaceScopedMixin):
    """One row of a task's log, in order: a ``message``, a ``compaction`` or an ``event``.

    The workflow assigns each row its sequence number and ``event_id``, so a
    retried append lands on the same row instead of adding one.
    """

    __tablename__ = "task_conversation_entries"
    __table_args__ = (
        UniqueConstraint("task_id", "seq", name="uq_task_conversation_entries_seq"),
        UniqueConstraint("task_id", "event_id", name="uq_task_conversation_entries_event"),
        CheckConstraint(
            "kind IN ('message', 'compaction', 'event')", name="ck_task_conversation_entries_kind"
        ),
    )

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attachments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    body_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
