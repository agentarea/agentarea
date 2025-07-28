"""add_user_id_fields_and_enforce_constraints

Revision ID: 69f44bd020a9
Revises: 4d4f1f91d2d9
Create Date: 2025-07-25 19:55:44.442900

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '69f44bd020a9'
down_revision: Union[str, None] = '4d4f1f91d2d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Get database connection to check existing columns
    connection = op.get_bind()
    
    # List of all tables that need user_id and workspace_id fields
    tables = [
        'agents', 'tasks', 'triggers', 'trigger_executions',
        'mcp_servers', 'mcp_server_instances', 
        'provider_configs', 'model_instances', 'provider_specs', 'model_specs',
        'llm_providers', 'llm_models', 'llm_model_instances'  # Legacy tables
    ]
    
    # Step 1: Add user_id columns to tables that don't have them yet
    # Check which tables already have user_id column
    for table in tables:
        # Check if user_id column exists
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if not result.fetchone():
            # Add user_id column as nullable first
            op.add_column(table, sa.Column('user_id', sa.String(255), nullable=True))
    
    # Step 2: Clean up records without proper workspace context
    # Set default values for existing records
    # In a real system, you'd want to map these to actual users/workspaces
    # For now, we'll use system defaults that can be updated later
    for table in tables:
        # Check if workspace_id column exists and update NULL values
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'workspace_id'
        """))
        
        if result.fetchone():
            # Update records with NULL workspace_id to use 'default' workspace
            connection.execute(
                sa.text(f"""
                    UPDATE {table} 
                    SET workspace_id = 'default' 
                    WHERE workspace_id IS NULL
                """)
            )
        
        # Check if user_id column exists and update NULL values
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if result.fetchone():
            # Check the data type of user_id column to determine appropriate default value
            column_type_result = connection.execute(sa.text(f"""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = 'user_id'
            """))
            
            column_type = column_type_result.fetchone()
            if column_type:
                data_type = column_type[0]
                
                if data_type == 'uuid':
                    # Use a system UUID for UUID columns
                    default_user_id = '00000000-0000-0000-0000-000000000000'
                else:
                    # Use 'system' for string columns
                    default_user_id = 'system'
                
                # Update records with NULL user_id
                connection.execute(
                    sa.text(f"""
                        UPDATE {table} 
                        SET user_id = '{default_user_id}' 
                        WHERE user_id IS NULL
                    """)
                )
    
    # Step 3: Make user_id and workspace_id non-nullable
    for table in tables:
        # Check if user_id column exists before making it non-nullable
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if result.fetchone():
            op.alter_column(table, 'user_id', nullable=False)
        
        # Check if workspace_id column exists before making it non-nullable
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'workspace_id'
        """))
        
        if result.fetchone():
            op.alter_column(table, 'workspace_id', nullable=False)
    
    # Step 4: Add indexes for efficient user and workspace filtering
    for table in tables:
        # Check if user_id column exists before creating indexes
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        has_user_id = result.fetchone() is not None
        
        # Check if workspace_id column exists
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'workspace_id'
        """))
        
        has_workspace_id = result.fetchone() is not None
        
        # Create indexes only for columns that exist
        if has_user_id:
            # Check if index already exists
            result = connection.execute(sa.text(f"""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = '{table}' AND indexname = 'idx_{table}_user_id'
            """))
            
            if not result.fetchone():
                op.create_index(f'idx_{table}_user_id', table, ['user_id'])
        
        if has_workspace_id:
            # Check if workspace_id index already exists
            result = connection.execute(sa.text(f"""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_id'
            """))
            
            if not result.fetchone():
                op.create_index(f'idx_{table}_workspace_id', table, ['workspace_id'])
        
        # Composite indexes for efficient workspace + user filtering
        if has_user_id and has_workspace_id:
            # Check if composite index already exists
            result = connection.execute(sa.text(f"""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_user'
            """))
            
            if not result.fetchone():
                op.create_index(f'idx_{table}_workspace_user', table, ['workspace_id', 'user_id'])
        
        # For some tables, add additional composite indexes for common queries
        if table in ['tasks', 'triggers', 'trigger_executions'] and has_workspace_id:
            # Check if workspace + created_at index already exists
            result = connection.execute(sa.text(f"""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_created'
            """))
            
            if not result.fetchone():
                # Add workspace + created_at index for time-based queries
                op.create_index(f'idx_{table}_workspace_created', table, ['workspace_id', 'created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # List of all tables that have user_id and workspace_id fields
    tables = [
        'agents', 'tasks', 'triggers', 'trigger_executions',
        'mcp_servers', 'mcp_server_instances', 
        'provider_configs', 'model_instances', 'provider_specs', 'model_specs',
        'llm_providers', 'llm_models', 'llm_model_instances'  # Legacy tables
    ]
    
    connection = op.get_bind()
    
    # Remove indexes first
    for table in tables:
        # Remove composite indexes if they exist
        if table in ['tasks', 'triggers', 'trigger_executions']:
            result = connection.execute(sa.text(f"""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_created'
            """))
            
            if result.fetchone():
                op.drop_index(f'idx_{table}_workspace_created', table)
        
        # Check and remove workspace_user composite index
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_workspace_user'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_workspace_user', table)
        
        # Check and remove user_id index
        result = connection.execute(sa.text(f"""
            SELECT indexname 
            FROM pg_indexes 
            WHERE tablename = '{table}' AND indexname = 'idx_{table}_user_id'
        """))
        
        if result.fetchone():
            op.drop_index(f'idx_{table}_user_id', table)
    
    # Make columns nullable again
    for table in tables:
        # Check if user_id column exists before making it nullable
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if result.fetchone():
            op.alter_column(table, 'user_id', nullable=True)
        
        # Check if workspace_id column exists before making it nullable
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'workspace_id'
        """))
        
        if result.fetchone():
            op.alter_column(table, 'workspace_id', nullable=True)
    
    # Remove user_id columns (but keep workspace_id as it was added in a previous migration)
    for table in tables:
        # Check if user_id column exists before dropping it
        result = connection.execute(sa.text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table}' AND column_name = 'user_id'
        """))
        
        if result.fetchone():
            op.drop_column(table, 'user_id')
