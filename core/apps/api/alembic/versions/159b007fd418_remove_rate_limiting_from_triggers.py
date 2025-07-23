"""remove_rate_limiting_from_triggers

Revision ID: 159b007fd418
Revises: 1c58f7ee64de
Create Date: 2025-07-24 01:37:09.357954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '159b007fd418'
down_revision: Union[str, None] = '1c58f7ee64de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Remove rate limiting column from triggers table."""
    # Remove max_executions_per_hour column as rate limiting is handled at infrastructure layer
    op.drop_column('triggers', 'max_executions_per_hour')


def downgrade() -> None:
    """Add back rate limiting column to triggers table."""
    # Add back max_executions_per_hour column for rollback
    op.add_column('triggers', sa.Column('max_executions_per_hour', sa.Integer(), nullable=False, server_default='60'))
