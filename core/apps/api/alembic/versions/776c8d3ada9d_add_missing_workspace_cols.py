"""add_missing_workspace_cols

Revision ID: 776c8d3ada9d
Revises: 9e1d75cd2eee
Create Date: 2025-07-30 02:03:00.000000

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '776c8d3ada9d'
down_revision: Union[str, None] = '9e1d75cd2eee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add workspace_id columns to LLM tables that don't have them yet."""
    
    # Check if workspace_id column exists in provider_specs table
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check provider_specs table
    provider_specs_columns = [col['name'] for col in inspector.get_columns('provider_specs')]
    if 'workspace_id' not in provider_specs_columns:
        op.add_column('provider_specs', sa.Column('workspace_id', sa.String(255), nullable=False, server_default='default'))
        op.create_index('ix_provider_specs_workspace_id', 'provider_specs', ['workspace_id'])
    
    # Check model_specs table
    model_specs_columns = [col['name'] for col in inspector.get_columns('model_specs')]
    if 'workspace_id' not in model_specs_columns:
        op.add_column('model_specs', sa.Column('workspace_id', sa.String(255), nullable=False, server_default='default'))
        op.create_index('ix_model_specs_workspace_id', 'model_specs', ['workspace_id'])


def downgrade() -> None:
    """Remove workspace_id columns from LLM tables."""
    
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    # Check provider_specs table
    provider_specs_columns = [col['name'] for col in inspector.get_columns('provider_specs')]
    if 'workspace_id' in provider_specs_columns:
        op.drop_index('ix_provider_specs_workspace_id', 'provider_specs')
        op.drop_column('provider_specs', 'workspace_id')
    
    # Check model_specs table
    model_specs_columns = [col['name'] for col in inspector.get_columns('model_specs')]
    if 'workspace_id' in model_specs_columns:
        op.drop_index('ix_model_specs_workspace_id', 'model_specs')
        op.drop_column('model_specs', 'workspace_id')
