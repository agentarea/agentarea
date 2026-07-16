"""add event outbox

Transactional outbox for domain-event publishing: a row is written in the same
transaction as the aggregate change, and a background relay later publishes it
to the broker and marks it published. Makes event delivery atomic with the state
change and removes the silent publish-error drop.

Revision ID: 20260716_1251_add_event_outbox
Revises: 20260702_0001_add_clients_tables
Create Date: 2026-07-16 12:51:14.010423
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260716_1251_add_event_outbox"
down_revision: str | None = "20260702_0001_add_clients_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(length=255), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("aggregate_id", sa.String(length=255), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_event_outbox_event_id"), "event_outbox", ["event_id"], unique=True
    )
    op.create_index(
        op.f("ix_event_outbox_aggregate_id"), "event_outbox", ["aggregate_id"], unique=False
    )
    op.create_index(
        op.f("ix_event_outbox_published_at"), "event_outbox", ["published_at"], unique=False
    )
    op.create_index(
        op.f("ix_event_outbox_workspace_id"), "event_outbox", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_event_outbox_created_by"), "event_outbox", ["created_by"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_event_outbox_created_by"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_workspace_id"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_published_at"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_aggregate_id"), table_name="event_outbox")
    op.drop_index(op.f("ix_event_outbox_event_id"), table_name="event_outbox")
    op.drop_table("event_outbox")
