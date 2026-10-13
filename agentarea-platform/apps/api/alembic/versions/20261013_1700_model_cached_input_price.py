"""model_specs.cached_input_cost_per_token: the price of a prompt token read from cache

Null prices cached prompt tokens as any other input token.

Revision ID: 20261013_1700_cached_input_price
Revises: 20261013_1500_conv_attachments
Create Date: 2026-10-13 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_1700_cached_input_price"
down_revision: str | None = "20261013_1500_conv_attachments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_specs",
        sa.Column("cached_input_cost_per_token", sa.Numeric(20, 12), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_specs", "cached_input_cost_per_token")
