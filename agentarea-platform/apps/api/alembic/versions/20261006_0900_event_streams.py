"""Event streams: named journals, webhook sources, fan-out subscriptions, outcomes

stream_events is range-partitioned by day on received_at; its primary key is
(sequence, received_at) because a partitioned table's unique keys must carry the
partition key. Novelty is decided by stream_event_keys. Partitions for the next
two weeks are created here; the worker keeps them ahead afterwards.

Revision ID: 20261006_0900_event_streams
Revises: 20261005_1500_item_hosting
Create Date: 2026-10-06
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_0900_event_streams"
down_revision: str | None = "20261005_1500_item_hosting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _scoped_columns() -> list[sa.Column]:
    return [
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    ]


def _partition_ddl(day: date) -> str:
    following = day + timedelta(days=1)
    return (
        f"CREATE TABLE IF NOT EXISTS stream_events_p{day:%Y%m%d} PARTITION OF stream_events "
        f"FOR VALUES FROM ('{day.isoformat()} 00:00:00+00') "
        f"TO ('{following.isoformat()} 00:00:00+00')"
    )


def upgrade() -> None:
    op.create_table(
        "streams",
        *_scoped_columns(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.UniqueConstraint("workspace_id", "name", name="uq_streams_workspace_name"),
    )
    op.create_table(
        "stream_sources",
        *_scoped_columns(),
        sa.Column(
            "stream_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("webhook_id", sa.String(255), nullable=True, unique=True),
        sa.Column("webhook_type", sa.String(50), nullable=True),
        sa.Column("allowed_methods", sa.JSON(), nullable=True),
        sa.Column("validation_rules", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("webhook_config", sa.JSON(), nullable=True),
        sa.Column("credential_key", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "kind <> 'webhook' OR (webhook_id IS NOT NULL AND webhook_type IS NOT NULL "
            "AND credential_key IS NOT NULL)",
            name="ck_stream_sources_webhook",
        ),
    )
    op.execute("CREATE SEQUENCE stream_events_sequence_seq AS bigint")
    op.execute(
        """
        CREATE TABLE stream_events (
            sequence bigint NOT NULL DEFAULT nextval('stream_events_sequence_seq'),
            received_at timestamptz NOT NULL,
            stream_id uuid NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
            event_id uuid NOT NULL,
            event_key text NOT NULL,
            kind varchar(255) NOT NULL,
            source varchar(512) NOT NULL,
            subject varchar(512),
            occurred_at timestamptz NOT NULL,
            correlation_id varchar(255),
            causation_id varchar(255),
            source_id uuid,
            depth integer NOT NULL DEFAULT 0,
            data jsonb NOT NULL,
            workspace_id varchar(255) NOT NULL,
            created_by varchar(255) NOT NULL,
            PRIMARY KEY (sequence, received_at)
        ) PARTITION BY RANGE (received_at)
        """
    )
    op.execute("ALTER SEQUENCE stream_events_sequence_seq OWNED BY stream_events.sequence")
    op.create_index("ix_stream_events_stream_sequence", "stream_events", ["stream_id", "sequence"])
    op.create_index(
        "ix_stream_events_workspace_received", "stream_events", ["workspace_id", "received_at"]
    )
    op.create_index("ix_stream_events_workspace_id", "stream_events", ["workspace_id"])
    op.create_index("ix_stream_events_created_by", "stream_events", ["created_by"])
    today = datetime.now(UTC).date()
    for offset in range(-1, 15):
        op.execute(_partition_ddl(today + timedelta(days=offset)))

    op.create_table(
        "stream_event_keys",
        sa.Column(
            "stream_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("event_key", sa.Text(), primary_key=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stream_event_keys_received_at", "stream_event_keys", ["received_at"])
    op.create_index(
        "ix_stream_event_keys_stream_sequence", "stream_event_keys", ["stream_id", "sequence"]
    )

    op.create_table(
        "stream_subscriptions",
        *_scoped_columns(),
        sa.Column(
            "stream_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column(
            "trigger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("triggers.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("filter", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("output_stream_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("cursor_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("leased_until", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(255), nullable=True),
        sa.CheckConstraint(
            "kind <> 'trigger' OR trigger_id IS NOT NULL", name="ck_stream_subscriptions_trigger"
        ),
    )
    op.create_index(
        "ix_stream_subscriptions_due", "stream_subscriptions", ["status", "next_attempt_at"]
    )

    op.create_table(
        "subscription_outcomes",
        *_scoped_columns(),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stream_subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stream_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("derived_sequences", sa.JSON(), nullable=False, server_default="[]"),
        sa.UniqueConstraint(
            "subscription_id", "event_sequence", name="uq_subscription_outcomes_event"
        ),
    )
    op.create_index(
        "ix_subscription_outcomes_stream_event",
        "subscription_outcomes",
        ["stream_id", "event_sequence"],
    )


def downgrade() -> None:
    op.drop_table("subscription_outcomes")
    op.drop_table("stream_subscriptions")
    op.drop_table("stream_event_keys")
    op.execute("DROP TABLE stream_events")
    op.execute("DROP SEQUENCE IF EXISTS stream_events_sequence_seq")
    op.drop_table("stream_sources")
    op.drop_table("streams")
