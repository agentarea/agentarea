"""MCP Events out: a stream's EXTERNAL subscriptions

An ``external`` row of ``stream_subscriptions`` is an MCP Events webhook
subscriber: the key's derived id (unique in the workspace), the subscriber
principal, the callback URL, the secret store entry holding its ``whsec_``
secret, when it expires unless refreshed, when its endpoint answered the
challenge, and how delivery to it is going.

Revision ID: 20261019_1600_mcp_events_out
Revises: 20261019_1400_mcp_events_in
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_1600_mcp_events_out"
down_revision: str | None = "20261019_1400_mcp_events_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    sa.Column("external_id", sa.String(64), nullable=True),
    sa.Column("subscriber", sa.String(255), nullable=True),
    sa.Column("callback_url", sa.Text(), nullable=True),
    sa.Column("secret_name", sa.String(255), nullable=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("last_error", sa.String(32), nullable=True),
    sa.Column("failed_since", sa.DateTime(timezone=True), nullable=True),
)


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("stream_subscriptions", column)
    op.create_check_constraint(
        "ck_stream_subscriptions_external",
        "stream_subscriptions",
        "kind <> 'external' OR (external_id IS NOT NULL AND subscriber IS NOT NULL "
        "AND callback_url IS NOT NULL AND secret_name IS NOT NULL AND expires_at IS NOT NULL)",
    )
    op.create_index(
        "uq_stream_subscriptions_external",
        "stream_subscriptions",
        ["workspace_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_stream_subscriptions_external", table_name="stream_subscriptions")
    op.drop_constraint("ck_stream_subscriptions_external", "stream_subscriptions", type_="check")
    for column in reversed(_COLUMNS):
        op.drop_column("stream_subscriptions", column.name)
