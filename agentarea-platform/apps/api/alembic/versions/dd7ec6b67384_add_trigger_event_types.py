"""add trigger event_types column

Revision ID: dd7ec6b67384
Revises: cc6ec6b67383
Create Date: 2026-03-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'dd7ec6b67384'
down_revision: Union[str, None] = 'cc6ec6b67383'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('triggers', sa.Column('event_types', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('triggers', 'event_types')
