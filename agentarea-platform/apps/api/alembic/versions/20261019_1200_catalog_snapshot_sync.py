"""Registries remember their source's ETag; catalog search drops its trigram indexes

A reconcile re-read and re-wrote every catalog row every hour whether or not
the source had changed. ``registries.source_etag`` lets a sync skip a source
whose ETag is the one it last applied.

The two pg_trgm indexes on ``registry_items`` (294 MB on RU) indexed every row,
including the 217k items no source published any more. Browse filters on the
partial ``registry_active`` indexes first and applies ILIKE to the few thousand
live rows; the planner did not pick the trigram indexes for it.

Revision ID: 20261019_1200_catalog_snapshot
Revises: 20261013_2200_drop_decide
Create Date: 2026-10-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_1200_catalog_snapshot"
down_revision: str | None = "20261013_2200_drop_decide"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("registries", sa.Column("source_etag", sa.Text(), nullable=True))
    for column in ("name", "description"):
        op.drop_index(f"ix_registry_items_{column}_trgm", table_name="registry_items")


def downgrade() -> None:
    for column in ("name", "description"):
        op.create_index(
            f"ix_registry_items_{column}_trgm",
            "registry_items",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    op.drop_column("registries", "source_etag")
