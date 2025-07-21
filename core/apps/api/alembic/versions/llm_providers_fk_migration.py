"""Add llm_providers table and provider_id foreign key to llm_models.

Revision ID: add_llm_providers_fk
Revises: b5ce5d3145b5
Create Date: 2025-05-17 00:00:00.000000
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "add_llm_providers_fk"
down_revision = "add_env_schema_mcp"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Create llm_providers table
    op.create_table(
        "llm_providers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("provider_type", sa.String(), nullable=False),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, default=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 2. Add provider_id to llm_models
    op.add_column(
        "llm_models", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False)
    )

    # 3. Add foreign key constraint
    op.create_foreign_key(
        "fk_llm_models_provider_id", "llm_models", "llm_providers", ["provider_id"], ["id"]
    )


def downgrade():
    # 1. Drop foreign key constraint
    op.drop_constraint("fk_llm_models_provider_id", "llm_models", type_="foreignkey")
    
    # 2. Drop provider_id column
    op.drop_column("llm_models", "provider_id")

    # 3. Drop llm_providers table
    op.drop_table("llm_providers")
