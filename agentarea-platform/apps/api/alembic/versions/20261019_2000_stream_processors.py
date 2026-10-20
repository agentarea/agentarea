"""Processors: a subscription that runs an agent's code over each event

A ``processor`` row of ``stream_subscriptions`` holds its Python in ``code``
and writes into its ``output_stream_ids``.

Revision ID: 20261019_2000_stream_processors
Revises: 20261019_1800_platform_stream
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_2000_stream_processors"
down_revision: str | None = "20261019_1800_platform_stream"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stream_subscriptions", sa.Column("code", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_stream_subscriptions_processor",
        "stream_subscriptions",
        "kind <> 'processor' OR code IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("DELETE FROM stream_subscriptions WHERE kind = 'processor'")
    op.drop_constraint("ck_stream_subscriptions_processor", "stream_subscriptions", type_="check")
    op.drop_column("stream_subscriptions", "code")
