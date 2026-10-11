"""ORM models for persisted governance policy rules and tool-call approvals."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
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
    managed_by: Mapped[str | None] = mapped_column(String(50), nullable=True)


class ToolCallApprovalORM(BaseModel, WorkspaceScopedMixin):
    """One exact tool call a client asked to run, held for a person's decision.

    ``created_by`` is the person whose client made the call.
    """

    __tablename__ = "tool_call_approvals"
    __table_args__ = (
        Index(
            "ix_tool_call_approvals_call",
            "workspace_id",
            "created_by",
            "tool",
            "arguments_hash",
        ),
        Index("ix_tool_call_approvals_workspace_status", "workspace_id", "status"),
    )

    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    client_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mcp_instance_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    connector: Mapped[str] = mapped_column(String(255), nullable=False)
    tool: Mapped[str] = mapped_column(String(255), nullable=False)
    policy_name: Mapped[str] = mapped_column(String(512), nullable=False)
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB_TYPE, nullable=False)
    arguments_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approvers: Mapped[list[str]] = mapped_column(JSONB_TYPE, nullable=False, default=list)
    decided_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# One open request per exact call: a concurrent retry finds it instead of adding one.
_PENDING = ToolCallApprovalORM.status == "pending"
Index(
    "uq_tool_call_approvals_pending",
    ToolCallApprovalORM.workspace_id,
    ToolCallApprovalORM.created_by,
    ToolCallApprovalORM.mcp_instance_id,
    ToolCallApprovalORM.tool,
    ToolCallApprovalORM.arguments_hash,
    unique=True,
    postgresql_where=_PENDING,
    sqlite_where=_PENDING,
)
