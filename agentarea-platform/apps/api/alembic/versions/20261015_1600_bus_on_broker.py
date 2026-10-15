"""The event bus moves onto the broker: stream_events becomes a read model

Events reach streams through the broker (a ``streams.events`` partition); the
``router`` group reacts to them and the ``events-view`` group writes them into
``stream_events``. What the Postgres journal and its dispatcher kept goes:
``stream_event_keys`` (ingest dedups by the deterministic event id), the
subscription cursor, lease and retry columns (the broker's consumer group holds
positions and redelivery), the per-stream ``retention_days`` (one deployment
retention, AGENTAREA_EVENT_RETENTION) and ``subscription_outcomes``, merged into
``trigger_executions``: one row per reaction of a subscription to a stream
event, unique per (subscription, event). A forward's reaction has no trigger, so
``trigger_id`` becomes nullable.

No customers: nothing is copied over.

Revision ID: 20261015_1600_bus_on_broker
Revises: 20261015_1500_drop_task_summary
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_1600_bus_on_broker"
down_revision: str | None = "20261015_1500_drop_task_summary"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISPATCH_COLUMNS = (
    "cursor_sequence",
    "attempts",
    "next_attempt_at",
    "last_error",
    "leased_until",
    "lease_owner",
)


def upgrade() -> None:
    op.drop_table("subscription_outcomes")
    op.drop_table("stream_event_keys")

    op.drop_index("ix_stream_subscriptions_due", table_name="stream_subscriptions")
    for column in _DISPATCH_COLUMNS:
        op.drop_column("stream_subscriptions", column)
    op.drop_column("streams", "retention_days")

    op.create_index(
        "uq_stream_events_event", "stream_events", ["event_id", "received_at"], unique=True
    )

    op.alter_column("trigger_executions", "trigger_id", nullable=True)
    op.add_column(
        "trigger_executions",
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stream_subscriptions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "trigger_executions", sa.Column("stream_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(
        "trigger_executions", sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("trigger_executions", sa.Column("verdict", sa.String(16), nullable=True))
    op.add_column("trigger_executions", sa.Column("reason", sa.Text(), nullable=True))
    op.add_column("trigger_executions", sa.Column("score", sa.Float(), nullable=True))
    op.add_column(
        "trigger_executions",
        sa.Column("derived_event_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column("trigger_executions", sa.Column("correlation_id", sa.String(255), nullable=True))
    op.add_column("trigger_executions", sa.Column("causation_id", sa.String(255), nullable=True))
    op.create_unique_constraint(
        "uq_trigger_executions_subscription_event",
        "trigger_executions",
        ["subscription_id", "event_id"],
    )
    op.create_index(
        "ix_trigger_executions_stream_event", "trigger_executions", ["stream_id", "event_id"]
    )
    op.create_index("ix_trigger_executions_correlation", "trigger_executions", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_trigger_executions_correlation", table_name="trigger_executions")
    op.drop_index("ix_trigger_executions_stream_event", table_name="trigger_executions")
    op.drop_constraint(
        "uq_trigger_executions_subscription_event", "trigger_executions", type_="unique"
    )
    for column in (
        "causation_id",
        "correlation_id",
        "derived_event_ids",
        "score",
        "reason",
        "verdict",
        "event_id",
        "stream_id",
        "subscription_id",
    ):
        op.drop_column("trigger_executions", column)
    op.execute("DELETE FROM trigger_executions WHERE trigger_id IS NULL")
    op.alter_column("trigger_executions", "trigger_id", nullable=False)

    op.drop_index("uq_stream_events_event", table_name="stream_events")

    op.add_column(
        "streams",
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.alter_column("streams", "retention_days", server_default=None)
    op.add_column(
        "stream_subscriptions",
        sa.Column("cursor_sequence", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "stream_subscriptions",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "stream_subscriptions", sa.Column("next_attempt_at", sa.DateTime(), nullable=True)
    )
    op.add_column("stream_subscriptions", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("stream_subscriptions", sa.Column("leased_until", sa.DateTime(), nullable=True))
    op.add_column("stream_subscriptions", sa.Column("lease_owner", sa.String(255), nullable=True))
    op.create_index(
        "ix_stream_subscriptions_due", "stream_subscriptions", ["status", "next_attempt_at"]
    )

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
        "subscription_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
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
