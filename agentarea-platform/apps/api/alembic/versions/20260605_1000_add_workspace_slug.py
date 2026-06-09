"""Add slug to workspaces (human-readable handle for /w/{slug} URLs)

Adds a globally-unique ``slug`` column. Backfills any pre-existing rows
with ``slug = id`` (ids are already unique) so the unique index and the
NOT NULL constraint apply cleanly to populated and empty tables alike.

Revision ID: 20260605_1000_add_workspace_slug
Revises: 20260605_0900_source_provenance
Create Date: 2026-06-05 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260605_1000_add_workspace_slug"
down_revision: str = "20260605_0900_source_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("slug", sa.String(120), nullable=True))
    op.execute("UPDATE workspaces SET slug = id WHERE slug IS NULL")
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.alter_column("workspaces", "slug", nullable=False)


def downgrade() -> None:
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_column("workspaces", "slug")
