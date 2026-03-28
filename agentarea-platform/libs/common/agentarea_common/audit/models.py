"""Audit event ORM model."""

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..base.models import BaseModel


class AuditEventORM(BaseModel):
    """Immutable audit event record.

    Append-only: rows must never be updated or deleted in production.
    Grant only INSERT and SELECT on this table.
    """

    __tablename__ = "audit_events"

    # Who
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="user"
    )  # user | service | system | api_key

    # Where
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_ip: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # What
    action: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # hierarchical: agent.create, mcp.config.update
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Changes (for mutations)
    changes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Context
    event_metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_events_actor", "workspace_id", "actor_id", "created_at"),
        Index(
            "ix_audit_events_resource",
            "workspace_id",
            "resource_type",
            "resource_id",
            "created_at",
        ),
        Index("ix_audit_events_action", "workspace_id", "action", "created_at"),
    )
