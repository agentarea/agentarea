"""make_endpoint_url_nullable_in_llm_models

Revision ID: 594618aa508d
Revises: 093214a8a503
Create Date: 2025-07-02 19:09:47.780903

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '594618aa508d'
down_revision: Union[str, None] = '093214a8a503'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Make endpoint_url nullable in llm_models table
    op.alter_column('llm_models', 'endpoint_url', nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Make endpoint_url not nullable again (with default empty string for existing records)
    op.execute("UPDATE llm_models SET endpoint_url = '' WHERE endpoint_url IS NULL")
    op.alter_column('llm_models', 'endpoint_url', nullable=False)
