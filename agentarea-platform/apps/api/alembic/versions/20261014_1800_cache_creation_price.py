"""model_specs.cache_creation_input_cost_per_token: the price of a prompt token written to cache

Null prices a cache write as any other input token.

Revision ID: 20261014_1800_cache_write_price
Revises: 20261014_1200_cost_not_price
Create Date: 2026-10-14 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_1800_cache_write_price"
down_revision: str | None = "20261014_1200_cost_not_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_specs",
        sa.Column("cache_creation_input_cost_per_token", sa.Numeric(20, 12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_specs", "cache_creation_input_cost_per_token")
