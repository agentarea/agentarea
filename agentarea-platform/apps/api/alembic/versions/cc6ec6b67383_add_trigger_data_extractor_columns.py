"""add trigger data_extractor columns

Revision ID: cc6ec6b67383
Revises: 009_merge_heads
Create Date: 2026-03-15 12:41:38.100169

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc6ec6b67383"
down_revision: str | None = "009_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("triggers", sa.Column("data_extractor", sa.String(100), nullable=True))
    op.add_column("triggers", sa.Column("data_extractor_config", sa.JSON(), nullable=True))
    op.add_column("triggers", sa.Column("data_extractor_state", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("triggers", "data_extractor_state")
    op.drop_column("triggers", "data_extractor_config")
    op.drop_column("triggers", "data_extractor")
