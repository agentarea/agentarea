"""persist catalog recommendation order

Browsing ordered by `featured DESC, sort_key` — and almost nothing is featured,
so /explore was alphabetical. The usefulness signal already exists upstream:
the curated skills artifact is published in GitHub-star order and the
connection/agent/bundle artifacts are authored best-first. That order was
discarded at sync time.

`registry_items.recommendation_rank` stores the item's curated position within
its source; `registries.recommendation_priority` weights whole sources, so an
opt-in bulk/community mirror cannot interleave its rank-0 entries with the
curated front page.

Existing rows get the neutral defaults (every item rank 0, every registry the
standard priority), which reproduces today's ordering exactly — `sort_key` and
`id` still break the ties. The post-migration `agentarea-api reconcile` writes
the real ranks and applies configured priorities.

Revision ID: 20260919_1000_catalog_rank
Revises: 20260917_1100_exec_fired_by
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_1000_catalog_rank"
down_revision: str | None = "20260917_1100_exec_fired_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mirrors DEFAULT_REGISTRY_PRIORITY in agentarea_registry.domain.models.
_DEFAULT_REGISTRY_PRIORITY = "100"


def upgrade() -> None:
    op.add_column(
        "registry_items",
        sa.Column("recommendation_rank", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "registries",
        sa.Column(
            "recommendation_priority",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(_DEFAULT_REGISTRY_PRIORITY),
        ),
    )


def downgrade() -> None:
    op.drop_column("registries", "recommendation_priority")
    op.drop_column("registry_items", "recommendation_rank")
