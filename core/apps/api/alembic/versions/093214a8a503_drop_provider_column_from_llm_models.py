"""drop_provider_column_from_llm_models

Revision ID: 093214a8a503
Revises: 1df4475ca99b
Create Date: 2025-07-02 14:56:48.400736

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '093214a8a503'
down_revision: Union[str, None] = '1df4475ca99b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the old provider column since we now use provider_id foreign key
    op.drop_column('llm_models', 'provider')


def downgrade() -> None:
    """Downgrade schema."""
    # Add back the provider column for rollback
    op.add_column('llm_models', sa.Column('provider', sa.String(), nullable=False))
