"""Stream tables. stream_events is range-partitioned by day on received_at."""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Sequence,
    String,
    Text,
    UniqueConstraint,
    func,
    literal,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

STREAM_EVENTS_SEQUENCE = Sequence("stream_events_sequence_seq")


class JournalBase(DeclarativeBase):
    """Journal tables keyed by sequence, not by a surrogate uuid; same metadata as BaseModel."""

    metadata = BaseModel.metadata


class StreamORM(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_streams_workspace_name"),)

    #: Governed by the authorization graph: creating one grants its creator.
    __graph_resource__ = True

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False)


class StreamSourceORM(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "stream_sources"
    __table_args__ = (
        CheckConstraint(
            (
                "kind <> 'webhook' OR (webhook_id IS NOT NULL AND webhook_type IS NOT NULL "
                + "AND credential_key IS NOT NULL)"
            ),
            name="ck_stream_sources_webhook",
        ),
    )

    stream_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("streams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    webhook_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    webhook_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    allowed_methods: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    validation_rules: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    webhook_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    credential_key: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)


class StreamEventORM(JournalBase, WorkspaceScopedMixin):
    __tablename__ = "stream_events"
    __table_args__ = (
        Index("ix_stream_events_stream_sequence", "stream_id", "sequence"),
        Index("ix_stream_events_workspace_received", "workspace_id", "received_at"),
        {"postgresql_partition_by": "RANGE (received_at)"},
    )

    # Not indexed alone: ix_stream_events_workspace_received leads with workspace_id.
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)

    sequence: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        # func, not Sequence.next_value(): the tenant-scope suite also builds this on SQLite.
        server_default=func.nextval(literal(STREAM_EVENTS_SEQUENCE.name, String)),
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    stream_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("streams.id", ondelete="CASCADE"), nullable=False
    )
    event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_key: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(512), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(512), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class StreamEventKeyORM(JournalBase):
    """First insert decides novelty; a partitioned table cannot hold this unique key."""

    __tablename__ = "stream_event_keys"
    __table_args__ = (
        Index("ix_stream_event_keys_received_at", "received_at"),
        Index("ix_stream_event_keys_stream_sequence", "stream_id", "sequence"),
    )

    stream_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("streams.id", ondelete="CASCADE"), primary_key=True
    )
    event_key: Mapped[str] = mapped_column(Text, primary_key=True)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StreamSubscriptionORM(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "stream_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "kind <> 'trigger' OR trigger_id IS NOT NULL", name="ck_stream_subscriptions_trigger"
        ),
        Index("ix_stream_subscriptions_due", "status", "next_attempt_at"),
    )

    stream_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("streams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # FK to triggers.id (ON DELETE CASCADE) exists in the migration only: streams must
    # not import the triggers library to declare it.
    trigger_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, unique=True
    )
    filter: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    output_stream_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cursor_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    leased_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SubscriptionOutcomeORM(BaseModel, WorkspaceScopedMixin):
    __tablename__ = "subscription_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "event_sequence", name="uq_subscription_outcomes_event"
        ),
        Index("ix_subscription_outcomes_stream_event", "stream_id", "event_sequence"),
    )

    subscription_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("stream_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
    )
    stream_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    task_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    derived_sequences: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
