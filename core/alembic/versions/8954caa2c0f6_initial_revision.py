"""initial revision

Revision ID: 8954caa2c0f6
Revises: 
Create Date: 2025-04-11 01:56:00.416187

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = '8954caa2c0f6'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create MCP servers table
    op.create_table(
        'mcp_servers',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('docker_image_url', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('tags', sa.ARRAY(sa.String()), nullable=False),
        sa.Column('status', sa.String(), nullable=False, default='inactive'),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('last_updated', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    
    # Create LLM models table
    op.create_table(
        'llm_models',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('model_type', sa.String(), nullable=False),
        sa.Column('endpoint_url', sa.String(), nullable=False),
        sa.Column('context_window', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, default='inactive'),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('last_updated', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    
    # Create LLM model instances table
    op.create_table(
        'llm_model_instances',
        sa.Column('id', UUID(), primary_key=True),
        sa.Column('model_id', UUID(), sa.ForeignKey('llm_models.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('api_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, default='inactive'),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('last_updated', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('llm_model_instances')
    op.drop_table('llm_models')
    op.drop_table('mcp_servers')
