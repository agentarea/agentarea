"""provider_specs mark the provider the platform itself hosts

The catalog flags that provider with first_party; the Models page lists it first
and badges it, reading the column, so the webapp never names a provider. Every
existing row is a third party until the catalog's next sync says otherwise.

Revision ID: 20261103_1300_first_party
Revises: 20261103_1200_cache_breakpoints
Create Date: 2026-11-03 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_1300_first_party"
down_revision: str | None = "20261103_1200_cache_breakpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_specs",
        sa.Column("is_first_party", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("provider_specs", "is_first_party")
