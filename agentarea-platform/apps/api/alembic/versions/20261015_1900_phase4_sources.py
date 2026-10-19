"""Sources from the catalog, the event envelope, triggers are cron or stream (ADR-0040 phase 4)

stream_sources: a source is a webhook or a poll source of a catalog entry
(``webhook_type`` is the entry's slug). The member's settings move from
``validation_rules`` into ``webhook_config``; ``allowed_methods`` and
``validation_rules`` go. Poll state (``poll_cursor``, ``polled_at``,
``poll_error``) and ``registered_url`` are written by the Go event-service
only; ``event_templates`` are a source's own kind / key / session_key.

stream_events: the envelope's ``source_type``, ``session_key``, ``sender`` and
``attachments``.

triggers: a webhook is a stream source plus a stream trigger, so every webhook
trigger becomes a stream trigger on the stream it already has (its source keeps
the trigger's id as credential key, so its stored credentials still resolve).
Polling triggers and cron triggers with an extractor are deleted: the Go
event-service polls sources. The webhook and extractor columns go; ``session``
holds the trigger's session setting. No customers: nothing else is carried over.

Revision ID: 20261015_1900_phase4_sources
Revises: 20261015_1800_cost_entries_chain
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_1900_phase4_sources"
down_revision: str | None = "20261015_1800_cost_entries_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRIGGER_COLUMNS_DROPPED = (
    "data_extractor",
    "data_extractor_config",
    "data_extractor_state",
    "webhook_id",
    "allowed_methods",
    "webhook_type",
    "validation_rules",
    "webhook_config",
    "event_types",
)


def upgrade() -> None:
    op.add_column("stream_sources", sa.Column("event_templates", sa.JSON(), nullable=True))
    op.add_column("stream_sources", sa.Column("poll_cursor", sa.Text(), nullable=True))
    op.add_column(
        "stream_sources", sa.Column("polled_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("stream_sources", sa.Column("poll_error", sa.Text(), nullable=True))
    op.add_column("stream_sources", sa.Column("registered_url", sa.Text(), nullable=True))
    op.execute(
        """
        UPDATE stream_sources SET webhook_config = (
            COALESCE(webhook_config::jsonb, '{}'::jsonb)
            || jsonb_strip_nulls(jsonb_build_object(
                'header', validation_rules::jsonb ->> 'signature_header',
                'algorithm', validation_rules::jsonb ->> 'signature_algorithm',
                'prefix', validation_rules::jsonb ->> 'signature_prefix',
                'shop_id', validation_rules::jsonb ->> 'shop_id'
            ))
        )::json
        """
    )
    op.execute(
        "UPDATE stream_sources SET webhook_type = 'generic_webhook' WHERE webhook_type = 'generic'"
    )
    op.drop_column("stream_sources", "validation_rules")
    op.drop_column("stream_sources", "allowed_methods")
    op.create_check_constraint(
        "ck_stream_sources_poll",
        "stream_sources",
        "kind <> 'poll' OR (webhook_id IS NULL AND webhook_type IS NOT NULL "
        "AND credential_key IS NOT NULL)",
    )

    op.add_column("stream_events", sa.Column("source_type", sa.String(64), nullable=True))
    op.add_column("stream_events", sa.Column("session_key", sa.String(512), nullable=True))
    op.add_column("stream_events", sa.Column("sender", sa.String(512), nullable=True))
    op.add_column(
        "stream_events",
        sa.Column(
            "attachments",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )

    op.execute(
        """
        DELETE FROM triggers
        WHERE trigger_type = 'polling'
           OR (trigger_type = 'cron' AND data_extractor IS NOT NULL)
           OR (trigger_type = 'webhook' AND id NOT IN (
                SELECT trigger_id FROM stream_subscriptions WHERE trigger_id IS NOT NULL))
        """
    )
    op.execute("UPDATE triggers SET trigger_type = 'stream' WHERE trigger_type = 'webhook'")
    for column in _TRIGGER_COLUMNS_DROPPED:
        op.drop_column("triggers", column)
    op.add_column("triggers", sa.Column("session", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("triggers", "session")
    op.add_column("triggers", sa.Column("event_types", sa.JSON(), nullable=True))
    op.add_column("triggers", sa.Column("webhook_config", sa.JSON(), nullable=True))
    op.add_column(
        "triggers",
        sa.Column("validation_rules", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column("triggers", sa.Column("webhook_type", sa.String(50), nullable=True))
    op.add_column("triggers", sa.Column("allowed_methods", sa.JSON(), nullable=True))
    op.add_column("triggers", sa.Column("webhook_id", sa.String(255), nullable=True))
    op.create_index("ix_triggers_webhook_id", "triggers", ["webhook_id"])
    op.add_column("triggers", sa.Column("data_extractor_state", sa.JSON(), nullable=True))
    op.add_column("triggers", sa.Column("data_extractor_config", sa.JSON(), nullable=True))
    op.add_column("triggers", sa.Column("data_extractor", sa.String(100), nullable=True))

    op.drop_column("stream_events", "attachments")
    op.drop_column("stream_events", "sender")
    op.drop_column("stream_events", "session_key")
    op.drop_column("stream_events", "source_type")

    op.drop_constraint("ck_stream_sources_poll", "stream_sources", type_="check")
    op.execute("DELETE FROM stream_sources WHERE kind = 'poll'")
    op.execute(
        "UPDATE stream_sources SET webhook_type = 'generic' WHERE webhook_type = 'generic_webhook'"
    )
    op.add_column("stream_sources", sa.Column("allowed_methods", sa.JSON(), nullable=True))
    op.add_column(
        "stream_sources",
        sa.Column("validation_rules", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.drop_column("stream_sources", "registered_url")
    op.drop_column("stream_sources", "poll_error")
    op.drop_column("stream_sources", "polled_at")
    op.drop_column("stream_sources", "poll_cursor")
    op.drop_column("stream_sources", "event_templates")
