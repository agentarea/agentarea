"""add_workspace_id_to_all_tables

Revision ID: 4d4f1f91d2d9
Revises: 159b007fd418
Create Date: 2025-07-24 20:36:09.683686

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4d4f1f91d2d9'
down_revision: Union[str, None] = '159b007fd418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add workspace_id columns to all main tables
    
    # Agents table
    op.add_column('agents', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_agents_workspace_id', 'agents', ['workspace_id'])
    
    # Tasks table  
    op.add_column('tasks', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_tasks_workspace_id', 'tasks', ['workspace_id'])
    
    # MCP servers table
    op.add_column('mcp_servers', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_mcp_servers_workspace_id', 'mcp_servers', ['workspace_id'])
    
    # MCP server instances table
    op.add_column('mcp_server_instances', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_mcp_server_instances_workspace_id', 'mcp_server_instances', ['workspace_id'])
    
    # Provider configs table
    op.add_column('provider_configs', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_provider_configs_workspace_id', 'provider_configs', ['workspace_id'])
    
    # Model instances table
    op.add_column('model_instances', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_model_instances_workspace_id', 'model_instances', ['workspace_id'])
    
    # Triggers table
    op.add_column('triggers', sa.Column('workspace_id', sa.String(255), nullable=True))
    op.create_index('idx_triggers_workspace_id', 'triggers', ['workspace_id'])


def downgrade() -> None:
    """Downgrade schema."""
    # Remove workspace_id columns and indexes from all tables
    
    # Remove indexes first
    op.drop_index('idx_triggers_workspace_id', 'triggers')
    op.drop_index('idx_model_instances_workspace_id', 'model_instances')
    op.drop_index('idx_provider_configs_workspace_id', 'provider_configs')
    op.drop_index('idx_mcp_server_instances_workspace_id', 'mcp_server_instances')
    op.drop_index('idx_mcp_servers_workspace_id', 'mcp_servers')
    op.drop_index('idx_tasks_workspace_id', 'tasks')
    op.drop_index('idx_agents_workspace_id', 'agents')
    
    # Remove columns
    op.drop_column('triggers', 'workspace_id')
    op.drop_column('model_instances', 'workspace_id')
    op.drop_column('provider_configs', 'workspace_id')
    op.drop_column('mcp_server_instances', 'workspace_id')
    op.drop_column('mcp_servers', 'workspace_id')
    op.drop_column('tasks', 'workspace_id')
    op.drop_column('agents', 'workspace_id')
