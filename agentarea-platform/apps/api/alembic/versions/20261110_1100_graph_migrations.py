"""Graph migrations record which one-shot graph steps have applied

``agentarea-api migrate`` runs, after the schema migration, every step of
``agentarea_api.graph_migrations`` not yet recorded here, and records each one
once it has applied (``agentarea_common.rebac.graph_migrations``).

Revision ID: 20261110_1100_graph_migrations
Revises: 20261110_1000_client_sandbox
Create Date: 2026-11-10 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261110_1100_graph_migrations"
down_revision: str | None = "20261110_1000_client_sandbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "graph_migrations",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("graph_migrations")
