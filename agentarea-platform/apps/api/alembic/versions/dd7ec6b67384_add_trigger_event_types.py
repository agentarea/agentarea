"""add trigger event_types column

Revision ID: dd7ec6b67384
Revises: cc6ec6b67383
Create Date: 2026-03-15 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dd7ec6b67384"
down_revision: str | None = "cc6ec6b67383"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("triggers", sa.Column("event_types", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("triggers", "event_types")
