"""merge_llm_and_trigger_migrations

Revision ID: 070978d618bb
Revises: create_new_llm_arch, d7f8e9a0b2c3
Create Date: 2025-07-23 01:05:44.787478

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '070978d618bb'
down_revision: Union[str, None] = ('create_new_llm_arch', 'd7f8e9a0b2c3')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
