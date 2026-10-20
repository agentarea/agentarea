"""MCP Events in: what an instance offers, and a webhook source's subscription

``mcp_server_instances.events`` holds the events extension settings and the
``events/list`` result, stored at verification (NULL when the server does not
advertise events). ``stream_sources.subscription_id`` and ``refresh_before``
are the remote subscription the Go source reconciler made for an
``mcp_events`` source in webhook mode, and when it must be refreshed.

Revision ID: 20261019_1400_mcp_events_in
Revises: 20261019_1000_event_routing
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261019_1400_mcp_events_in"
down_revision: str | None = "20261019_1000_event_routing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_instances",
        sa.Column("events", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("stream_sources", sa.Column("subscription_id", sa.Text(), nullable=True))
    op.add_column(
        "stream_sources", sa.Column("refresh_before", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("stream_sources", "refresh_before")
    op.drop_column("stream_sources", "subscription_id")
    op.drop_column("mcp_server_instances", "events")
