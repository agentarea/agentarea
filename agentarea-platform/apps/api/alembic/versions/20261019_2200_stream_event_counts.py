"""stream_event_counts: events per stream, UTC day and source type, for the feed's facets

The workspace feed's counts per stream and per source type were a GROUP BY
over every stream_events row of the workspace on each first page. They are
read from this rollup instead, kept by the transaction that records each
event and cut a day at a time with the partitions. ``source_type`` is '' for
events of no source type, so it can be part of the key.

The backfill counts what is recorded now. stream_events is locked against
writes while it runs, so no insert falls between the count and the code that
keeps it.

Revision ID: 20261019_2200_event_counts
Revises: 20261019_2100_trigger_batch
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261019_2200_event_counts"
down_revision: str | None = "20261019_2100_trigger_batch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = """
INSERT INTO stream_event_counts (workspace_id, created_by, stream_id, day, source_type, count)
SELECT
    workspace_id,
    min(created_by),
    stream_id,
    (received_at AT TIME ZONE 'UTC')::date,
    coalesce(source_type, ''),
    count(*)
FROM stream_events
GROUP BY workspace_id, stream_id, (received_at AT TIME ZONE 'UTC')::date, coalesce(source_type, '')
ON CONFLICT (workspace_id, stream_id, day, source_type) DO UPDATE SET count = EXCLUDED.count
"""


def upgrade() -> None:
    op.create_table(
        "stream_event_counts",
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column(
            "stream_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("streams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "stream_id", "day", "source_type"),
    )
    op.execute("LOCK TABLE stream_events IN SHARE MODE")
    op.execute(BACKFILL)


def downgrade() -> None:
    op.drop_table("stream_event_counts")
