"""ORM models for persisted governance policies."""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

JSONB_TYPE = JSONB().with_variant(JSON(), "sqlite")


class GovernancePolicyORM(BaseModel, WorkspaceScopedMixin):
    """Source governance policy for a workspace, agent, or task scope."""

    __tablename__ = "governance_policies"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "scope_type",
            "scope_id",
            name="uq_governance_policies_scope",
        ),
    )

    scope_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    scope_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


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
