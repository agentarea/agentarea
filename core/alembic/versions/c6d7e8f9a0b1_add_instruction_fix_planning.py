"""add instruction field and fix planning type

Revision ID: c6d7e8f9a0b1
Revises: b5ce5d3145b5
Create Date: 2025-01-21 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5ce5d3145b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add instruction field
    op.add_column('agents', sa.Column('instruction', sa.String(), nullable=True))
    
    # Change planning field from String to Boolean
    # Use USING clause to handle the conversion properly
    op.execute("ALTER TABLE agents ALTER COLUMN planning TYPE BOOLEAN USING CASE WHEN planning = 'true' THEN true WHEN planning = 'false' THEN false ELSE null END")


def downgrade() -> None:
    """Downgrade schema."""
    # Change planning field back from Boolean to String
    op.execute("ALTER TABLE agents ALTER COLUMN planning TYPE VARCHAR USING CASE WHEN planning = true THEN 'true' WHEN planning = false THEN 'false' ELSE null END")
    
    # Remove instruction field
    op.drop_column('agents', 'instruction') 