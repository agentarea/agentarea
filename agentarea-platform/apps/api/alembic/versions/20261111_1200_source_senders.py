"""A source that admits senders chooses who may write to it

Revision ID: 20261111_1200_source_senders
Revises: 20261110_1100_graph_migrations
Create Date: 2026-11-11 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261111_1200_source_senders"
down_revision: str | None = "20261110_1100_graph_migrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stream_sources", sa.Column("senders", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("stream_sources", "senders")
