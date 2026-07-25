"""Transactional outbox ORM model.

A row is written in the SAME database transaction as the aggregate change that
produced the event. A background relay later reads unpublished rows, publishes
them to the broker, and marks them published. This makes domain-event delivery
atomic with the state change: a rolled-back transaction leaves no orphan event,
and a publish failure cannot silently drop an event (the row stays for retry).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON


class EventOutbox(BaseModel, WorkspaceScopedMixin):
    """Pending domain events awaiting publication by the relay."""

    __tablename__ = "event_outbox"

    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB().with_variant(JSON(), "sqlite"), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
