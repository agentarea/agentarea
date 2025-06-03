"""merge heads

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1, add_llm_providers_fk
Create Date: 2025-01-21 12:30:00.000000

"""
from typing import Sequence, Union, Tuple


# revision identifiers, used by Alembic.
revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None, Tuple[str, ...]] = ('c6d7e8f9a0b1', 'add_llm_providers_fk')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Merge heads - no additional changes needed."""
    pass


def downgrade() -> None:
    """Merge heads - no additional changes needed."""
    pass 