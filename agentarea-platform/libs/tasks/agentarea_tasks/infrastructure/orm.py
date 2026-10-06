"""Task ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, UniqueConstraint, func, text
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


class TaskEventORM(EventBaseModel, WorkspaceScopedMixin):
    """Task event ORM model for event sourcing."""

    __tablename__ = "task_events"

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})


class TaskConversationEntryORM(EventBaseModel, WorkspaceScopedMixin):
    """One entry of the conversation a task's model sees, in order.

    The workflow writes each entry at a sequence number it assigns, so a retried
    write lands on the same row instead of adding one.
    """

    __tablename__ = "task_conversation_entries"
    __table_args__ = (UniqueConstraint("task_id", "seq", name="uq_task_conversation_entries_seq"),)

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
