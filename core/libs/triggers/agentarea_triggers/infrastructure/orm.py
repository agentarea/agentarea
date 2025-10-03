"""Trigger ORM models."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import AuditMixin, BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship


class TriggerORM(BaseModel, WorkspaceScopedMixin, AuditMixin):
    """Trigger ORM model with workspace awareness and audit trail."""

    __tablename__ = "triggers"

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

    # Cron-specific fields
    cron_expression: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(100), nullable=True, default="UTC")
    next_run_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Webhook-specific fields
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    allowed_methods: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    webhook_type: Mapped[str | None] = mapped_column(String(50), nullable=True, default="generic")
    validation_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)

    # Generic webhook configuration - supports any webhook type
    webhook_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

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

    # Basic execution fields
    trigger_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("triggers.id", ondelete="CASCADE"), nullable=False
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

    # Relationship to trigger
    trigger: Mapped["TriggerORM"] = relationship("TriggerORM", back_populates="executions")

    def __repr__(self) -> str:
        """Return string representation."""
        return f"<TriggerExecutionORM {self.id}: {self.trigger_id} ({self.status})>"
