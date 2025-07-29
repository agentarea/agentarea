"""add_updated_by_to_mcp_servers

Revision ID: 7f580e33ddd7
Revises: 9e1d75cd2eee
Create Date: 2025-07-29 23:01:23.574910

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f580e33ddd7'
down_revision: Union[str, None] = '9e1d75cd2eee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add updated_by column to mcp_servers table."""
    # Check if updated_by column exists in mcp_servers table
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check mcp_servers table
    mcp_servers_columns = [col['name'] for col in inspector.get_columns('mcp_servers')]
    if 'updated_by' not in mcp_servers_columns:
        op.add_column('mcp_servers', sa.Column('updated_by', sa.String(255), nullable=True))
        op.create_index('ix_mcp_servers_updated_by', 'mcp_servers', ['updated_by'])


def downgrade() -> None:
    """Remove updated_by column from mcp_servers table."""
    # Check if updated_by column exists before trying to remove it
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check mcp_servers table
    mcp_servers_columns = [col['name'] for col in inspector.get_columns('mcp_servers')]
    if 'updated_by' in mcp_servers_columns:
        op.drop_index('ix_mcp_servers_updated_by', 'mcp_servers')
        op.drop_column('mcp_servers', 'updated_by')
