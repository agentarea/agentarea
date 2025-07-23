"""update_trigger_schema_for_scalability

Revision ID: 1c58f7ee64de
Revises: 070978d618bb
Create Date: 2025-07-24 00:26:27.565438

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c58f7ee64de'
down_revision: Union[str, None] = '070978d618bb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add the new generic webhook_config column
    op.add_column('triggers', sa.Column('webhook_config', sa.JSON(), nullable=True))
    
    # Migrate existing data from separate config fields to generic webhook_config
    # This ensures backward compatibility during migration
    connection = op.get_bind()
    
    # Update triggers with telegram_config
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET webhook_config = telegram_config 
            WHERE telegram_config IS NOT NULL
        """)
    )
    
    # Update triggers with slack_config (if no webhook_config already set)
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET webhook_config = slack_config 
            WHERE slack_config IS NOT NULL AND webhook_config IS NULL
        """)
    )
    
    # Update triggers with github_config (if no webhook_config already set)
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET webhook_config = github_config 
            WHERE github_config IS NOT NULL AND webhook_config IS NULL
        """)
    )
    
    # For triggers with multiple configs, merge them into a single config
    # This handles edge cases where multiple configs exist
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET webhook_config = jsonb_build_object(
                'telegram', telegram_config,
                'slack', slack_config,
                'github', github_config
            )
            WHERE (telegram_config IS NOT NULL AND slack_config IS NOT NULL) 
               OR (telegram_config IS NOT NULL AND github_config IS NOT NULL)
               OR (slack_config IS NOT NULL AND github_config IS NOT NULL)
        """)
    )
    
    # Drop the old separate config columns
    op.drop_column('triggers', 'telegram_config')
    op.drop_column('triggers', 'slack_config')
    op.drop_column('triggers', 'github_config')


def downgrade() -> None:
    """Downgrade schema."""
    # Add back the separate config columns
    op.add_column('triggers', sa.Column('telegram_config', sa.JSON(), nullable=True))
    op.add_column('triggers', sa.Column('slack_config', sa.JSON(), nullable=True))
    op.add_column('triggers', sa.Column('github_config', sa.JSON(), nullable=True))
    
    # Migrate data back from generic webhook_config to separate fields
    connection = op.get_bind()
    
    # Handle cases where webhook_config contains nested configs
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET telegram_config = (webhook_config->>'telegram')::json
            WHERE webhook_config ? 'telegram'
        """)
    )
    
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET slack_config = (webhook_config->>'slack')::json
            WHERE webhook_config ? 'slack'
        """)
    )
    
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET github_config = (webhook_config->>'github')::json
            WHERE webhook_config ? 'github'
        """)
    )
    
    # Handle cases where webhook_config is a direct config (not nested)
    # Assume it's telegram config if webhook_type is telegram, etc.
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET telegram_config = webhook_config
            WHERE webhook_type = 'telegram' 
              AND NOT (webhook_config ? 'telegram' OR webhook_config ? 'slack' OR webhook_config ? 'github')
        """)
    )
    
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET slack_config = webhook_config
            WHERE webhook_type = 'slack' 
              AND NOT (webhook_config ? 'telegram' OR webhook_config ? 'slack' OR webhook_config ? 'github')
        """)
    )
    
    connection.execute(
        sa.text("""
            UPDATE triggers 
            SET github_config = webhook_config
            WHERE webhook_type = 'github' 
              AND NOT (webhook_config ? 'telegram' OR webhook_config ? 'slack' OR webhook_config ? 'github')
        """)
    )
    
    # Drop the generic webhook_config column
    op.drop_column('triggers', 'webhook_config')
