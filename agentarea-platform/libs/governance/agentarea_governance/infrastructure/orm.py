"""ORM models for persisted governance policy rules and task snapshots."""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

JSONB_TYPE = JSONB().with_variant(JSON(), "sqlite")


class PolicyRuleORM(BaseModel, WorkspaceScopedMixin):
    """A single unified governance rule scoped to a subject."""

    __tablename__ = "policies"
    __table_args__ = (
        Index(
            "ix_policies_workspace_subject",
            "workspace_id",
            "subject_type",
            "subject_id",
        ),
    )

    subject_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    effect: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False, default=dict)
    condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TaskPolicySnapshotORM(BaseModel, WorkspaceScopedMixin):
    """Immutable effective policy snapshot for a task."""

    __tablename__ = "task_policy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "task_id",
            name="uq_task_policy_snapshots_task",
        ),
    )

    task_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    effective_policy: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False)
    source_policy_ids: Mapped[list[str]] = mapped_column(JSONB_TYPE, nullable=False, default=list)
    resolver_version: Mapped[str] = mapped_column(String(100), nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
