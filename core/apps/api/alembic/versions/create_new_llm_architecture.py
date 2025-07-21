"""Create new 4-entity LLM architecture

Revision ID: create_new_llm_arch
Revises: 594618aa508d
Create Date: 2025-01-21 12:00:00.000000

"""
from typing import Sequence, Union
import uuid
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'create_new_llm_arch'
down_revision: Union[str, None] = '594618aa508d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade to new 4-entity architecture."""
    
    # 1. Create provider_specs table (replaces llm_providers)
    op.create_table(
        'provider_specs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('provider_key', sa.String(), nullable=False, unique=True),  # openai, anthropic
        sa.Column('name', sa.String(), nullable=False),  # OpenAI, Anthropic
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('provider_type', sa.String(), nullable=False),  # for LiteLLM
        sa.Column('icon', sa.String(), nullable=True),
        sa.Column('is_builtin', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 2. Create provider_configs table (user configurations of providers)
    op.create_table(
        'provider_configs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('provider_spec_id', postgresql.UUID(as_uuid=True), 
                 sa.ForeignKey('provider_specs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),  # "My OpenAI", "Work OpenAI"
        sa.Column('api_key', sa.String(), nullable=False),
        sa.Column('endpoint_url', sa.String(), nullable=True),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=True),  # Future: FK to users
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 3. Create model_specs table (available models for each provider spec)
    op.create_table(
        'model_specs',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('provider_spec_id', postgresql.UUID(as_uuid=True), 
                 sa.ForeignKey('provider_specs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),  # gpt-4, claude-3-opus
        sa.Column('display_name', sa.String(), nullable=False),  # GPT-4, Claude 3 Opus
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('context_window', sa.Integer(), nullable=False, default=4096),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Add unique constraint for provider_spec_id + model_name
    op.create_unique_constraint(
        'uq_model_specs_provider_model', 'model_specs', ['provider_spec_id', 'model_name']
    )

    # 4. Create model_instances table (active user model instances)
    op.create_table(
        'model_instances',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('provider_config_id', postgresql.UUID(as_uuid=True), 
                 sa.ForeignKey('provider_configs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_spec_id', postgresql.UUID(as_uuid=True), 
                 sa.ForeignKey('model_specs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),  # User-friendly name
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('is_public', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    """Downgrade to old architecture."""
    op.drop_table('model_instances')
    op.drop_table('model_specs')
    op.drop_table('provider_configs')
    op.drop_table('provider_specs') 