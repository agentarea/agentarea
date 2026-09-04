"""Task ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, DateTime, Index, String, Text, text
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


class TaskEventORM(EventBaseModel, WorkspaceScopedMixin):
    """Task event ORM model for event sourcing."""

    __tablename__ = "task_events"

    task_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default={})
