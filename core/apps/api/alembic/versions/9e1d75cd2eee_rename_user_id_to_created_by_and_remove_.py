"""rename_user_id_to_created_by_and_remove_updated_by

Revision ID: 9e1d75cd2eee
Revises: 69f44bd020a9
Create Date: 2025-07-26 15:30:35.973061

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e1d75cd2eee'
down_revision: Union[str, None] = '69f44bd020a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Get database connection to check existing columns
    connection = op.get_bind()
    
    # List of all tables that have user_id field to rename
    tables = [
        'agents', 'tasks', 'triggers', 'trigger_executions',
        'mcp_servers', 'mcp_server_instances', 
        'provider_configs', 'model_instances', 'provider_specs', 'model_specs',
        'llm_providers', 'llm_models', 'llm_model_instances'  # Legacy tables
    ]
    
    # Step 1: Rename user_id columns to created_by (but handle tables that already have created_by)
    for table in tables:
        # Check if user_id column exists
        user_id_result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        # Check if created_by column already exists
        created_by_result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'created_by'
        """))
        
        has_user_id = user_id_result.fetchone() is not None
        has_created_by = created_by_result.fetchone() is not None
        
        if has_user_id and not has_created_by:
            # Simple rename: user_id -> created_by
            op.alter_column(table, 'user_id', new_column_name='created_by')
        elif has_user_id and has_created_by:
            # Table has both columns (from AuditMixin), need to merge data and drop user_id
            # Copy user_id data to created_by where created_by is null
            connection.execute(sa.text(f"""
                UPDATE {table} 
                SET created_by = user_id 
                WHERE created_by IS NULL AND user_id IS NOT NULL
            """))
            # Drop the user_id column
            op.drop_column(table, 'user_id')
    
    # Step 2: Remove updated_by columns where they exist
    for table in tables:
        # Check if updated_by column exists
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'updated_by'
        """))
        
        if result.fetchone():
            # Drop updated_by column
            op.drop_column(table, 'updated_by')
    
    # Step 3: Update indexes - drop old user_id indexes and create new created_by indexes
    for table in tables:
        # Check if old user_id index exists and drop it
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_user_id'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_user_id', table)
        
        # Check if workspace_user composite index exists and drop it
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_user'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_workspace_user', table)
        
        # Create new created_by index
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'created_by'
        """))
        
        if result.fetchone():
            # Create new indexes with created_by
            op.create_index(f'idx_{table}_created_by', table, ['created_by'])
            
            # Create new composite index for workspace + created_by
            result = connection.execute(sa.text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = 'workspace_id'
            """))
            
            if result.fetchone():
                op.create_index(f'idx_{table}_workspace_created_by', table, ['workspace_id', 'created_by'])


def downgrade() -> None:
    """Downgrade schema."""
    # Get database connection to check existing columns
    connection = op.get_bind()
    
    # List of all tables that have created_by field to rename back
    tables = [
        'agents', 'tasks', 'triggers', 'trigger_executions',
        'mcp_servers', 'mcp_server_instances', 
        'provider_configs', 'model_instances', 'provider_specs', 'model_specs',
        'llm_providers', 'llm_models', 'llm_model_instances'  # Legacy tables
    ]
    
    # Step 1: Drop new indexes
    for table in tables:
        # Drop created_by index
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_created_by'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_created_by', table)
        
        # Drop workspace + created_by composite index
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_created_by'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_workspace_created_by', table)
    
    # Step 2: Restore user_id columns (handle tables that originally had both columns)
    tables_with_audit_mixin = ['agents', 'mcp_servers', 'triggers']  # Tables that use AuditMixin
    
    for table in tables:
        # Check if created_by column exists
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'created_by'
        """))
        
        if result.fetchone():
            if table in tables_with_audit_mixin:
                # Table originally had both columns, restore user_id column
                op.add_column(table, sa.Column('user_id', sa.String(255), nullable=False, server_default='system'))
                # Copy created_by data to user_id
                connection.execute(sa.text(f"""
                    UPDATE {table} 
                    SET user_id = created_by
                """))
                # Remove server default
                op.alter_column(table, 'user_id', server_default=None)
            else:
                # Table originally only had user_id, rename back
                op.alter_column(table, 'created_by', new_column_name='user_id')
    
    # Step 3: Add back updated_by columns (as nullable)
    for table in tables:
        # Add updated_by column back
        op.add_column(table, sa.Column('updated_by', sa.String(255), nullable=True))
    
    # Step 4: Recreate old indexes
    for table in tables:
        # Check if user_id column exists (after rename)
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if result.fetchone():
            # Recreate old indexes
            op.create_index(f'idx_{table}_user_id', table, ['user_id'])
            
            # Recreate workspace + user composite index
            result = connection.execute(sa.text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = 'workspace_id'
            """))
            
            if result.fetchone():
                op.create_index(f'idx_{table}_workspace_user', table, ['workspace_id', 'user_id'])
