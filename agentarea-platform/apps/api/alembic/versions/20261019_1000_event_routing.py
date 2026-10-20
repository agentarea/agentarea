"""stream_events carry what the router did with them: routing and a tally of reactions

``routed_at`` and ``subscribers`` say when the router matched an event's
subscriptions and how many matched (0 included); ``reacted``, ``skipped`` and
``errors`` tally the reactions recorded since. The tally lives on the event
because deleting a subscription deletes its reactions. Events recorded before
this are routed at their arrival, to the subscriptions that reacted.

The workspace feed reads newest first by sequence within a workspace.

stream_subscriptions.started_at: when a subscription started taking events, set
by the database (created_at is a naive local time). The router never hands it
an event received earlier. Existing rows start at their created_at, read as UTC.

Revision ID: 20261019_1000_event_routing
Revises: 20261015_1900_phase4_sources
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_1000_event_routing"
down_revision: str | None = "20261015_1900_phase4_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = """
UPDATE stream_events AS e SET
    routed_at = e.received_at,
    subscribers = t.reacted,
    reacted = t.reacted,
    skipped = t.skipped,
    errors = t.errors
FROM (
    SELECT
        r.workspace_id,
        r.stream_id,
        r.event_id,
        count(*) AS reacted,
        count(*) FILTER (WHERE r.verdict = 'skipped') AS skipped,
        count(*) FILTER (WHERE r.verdict = 'error') AS errors
    FROM trigger_executions AS r
    WHERE r.subscription_id IS NOT NULL AND r.event_id IS NOT NULL
    GROUP BY r.workspace_id, r.stream_id, r.event_id
) AS t
WHERE t.event_id = e.event_id
  AND t.stream_id = e.stream_id
  AND t.workspace_id = e.workspace_id
"""
UNREACHED = (
    "UPDATE stream_events SET routed_at = received_at, subscribers = 0 WHERE routed_at IS NULL"
)


def upgrade() -> None:
    op.add_column(
        "stream_events", sa.Column("routed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("stream_events", sa.Column("subscribers", sa.Integer(), nullable=True))
    for column in ("reacted", "skipped", "errors"):
        op.add_column(
            "stream_events",
            sa.Column(column, sa.Integer(), nullable=False, server_default=sa.text("0")),
        )
    op.execute(BACKFILL)
    op.execute(UNREACHED)
    op.create_index(
        "ix_stream_events_workspace_sequence", "stream_events", ["workspace_id", "sequence"]
    )
    op.add_column(
        "stream_subscriptions",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE stream_subscriptions SET started_at = created_at AT TIME ZONE 'UTC'")
    op.alter_column(
        "stream_subscriptions",
        "started_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    op.drop_column("stream_subscriptions", "started_at")
    op.drop_index("ix_stream_events_workspace_sequence", table_name="stream_events")
    for column in ("errors", "skipped", "reacted", "subscribers", "routed_at"):
        op.drop_column("stream_events", column)
