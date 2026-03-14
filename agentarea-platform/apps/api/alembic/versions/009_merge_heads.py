"""merge_skill_members_and_registries

Revision ID: c2fd87a47d9b
Revises: 008_add_skill_members_table, 008_add_registries
Create Date: 2026-03-13 19:34:25.075743

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009_merge_heads'
down_revision: Union[str, None] = ('008_add_skill_members_table', '008_add_registries')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
