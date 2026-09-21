"""Immutable usage facts, with no dependency on a runtime object's lifetime."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Identity,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from agentarea_common.base.models import BaseModel


@BaseModel.registry.mapped
class ResourceUsageEvent:
    """Read model on the shared metadata; no mutable entity fields or foreign keys."""

    __tablename__ = "resource_usage_events"

    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[str] = mapped_column(Text, nullable=False)
    resource_kind: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    incarnation_id: Mapped[str] = mapped_column(Text, nullable=False)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    occurred_at_source: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("source", "event_id", name="uq_resource_usage_events_identity"),
        CheckConstraint(
            "workspace_id <> '' OR resource_kind = 'platform_runtime'",
            name="ck_resource_usage_events_workspace",
        ),
        # Postgres-only DDL: the shared metadata is also created on SQLite by the
        # unit-test fixtures, and jsonb_typeof does not exist there -- without the
        # guard one unreachable constraint fails create_all for every table.
        CheckConstraint(
            "jsonb_typeof(data) = 'object'", name="ck_resource_usage_events_data"
        ).ddl_if(dialect="postgresql"),
        Index("ix_resource_usage_events_workspace_sequence", "workspace_id", "sequence"),
        Index("ix_resource_usage_events_workspace_occurred", "workspace_id", "occurred_at"),
        Index(
            "ix_resource_usage_storage_scope",
            text("(data ->> 'storage_namespace')"),
            "workspace_id",
            "task_id",
            "resource_kind",
            text("sequence DESC"),
            postgresql_where=text(
                "kind IN ('storage.sample','storage.artifact.published') "
                "AND source IN ('storage-inventory','artifact-store')"
            ),
        ),
    )
