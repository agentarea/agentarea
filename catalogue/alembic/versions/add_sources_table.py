"""add sources table

Revision ID: add_sources_table
Revises: initial_migration
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'add_sources_table'
down_revision = 'initial_migration'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_table(
        'sources',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('configuration', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('meta_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False),
        sa.Column('updated_at', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('owner', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('source_id')
    )
    op.create_index(op.f('ix_sources_source_id'), 'sources', ['source_id'], unique=True)

def downgrade() -> None:
    op.drop_index(op.f('ix_sources_source_id'), table_name='sources')
    op.drop_table('sources') 