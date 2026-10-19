"""Trigger ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import AuditMixin, BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class TriggerORM(BaseModel, WorkspaceScopedMixin, AuditMixin):
    """Trigger ORM model with workspace awareness and audit trail."""

    __tablename__ = "triggers"

    #: Governed by the authorization graph: creating one writes
    #: ``resource:<id>`` tuples so its creator can reach it afterwards.
    __graph_resource__ = True

    # Basic trigger fields
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    task_parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    conditions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Business logic safety
    failure_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_execution_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Set when the person who configured this trigger can no longer run its agent.
    needs_new_owner_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Cron-specific fields
    cron_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True, default="UTC")

    #: ``{"continue": bool, "idle_timeout": "30m"}`` for a stream trigger; null = the defaults.
    session: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relationship to executions
    executions: Mapped[list["TriggerExecutionORM"]] = relationship(
        "TriggerExecutionORM",
        back_populates="trigger",
        cascade="all, delete-orphan",
        order_by="TriggerExecutionORM.executed_at.desc()",
    )

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<TriggerORM {self.id}: {self.name} ({self.trigger_type})>"


class TriggerExecutionORM(BaseModel, WorkspaceScopedMixin):
    """Trigger execution ORM model with workspace awareness."""

    __tablename__ = "trigger_executions"

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "event_id", name="uq_trigger_executions_subscription_event"
        ),
        Index("ix_trigger_executions_stream_event", "stream_id", "event_id"),
        Index("ix_trigger_executions_correlation", "correlation_id"),
    )

    # Basic execution fields. A forward's reaction to a stream event has no trigger.
    trigger_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("triggers.id", ondelete="CASCADE"), nullable=True
    )
    executed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Temporal workflow tracking
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The principal who asked for this one run, when a person did. NULL means the
    # trigger fired itself. created_by cannot answer this: it is filled for every
    # execution, including the ones the scheduler writes.
    fired_by: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # A reaction of a stream subscription to a bus event: one per (subscription,
    # event). The FK to stream_subscriptions (ON DELETE CASCADE) exists in the
    # migration only, as stream_subscriptions' FK to triggers does.
    subscription_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    stream_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    event_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    derived_event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationship to trigger
    trigger: Mapped["TriggerORM"] = relationship("TriggerORM", back_populates="executions")

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<TriggerExecutionORM {self.id}: {self.trigger_id} ({self.status})>"
