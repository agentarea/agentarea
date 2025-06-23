"""Add llm_providers table and provider_id foreign key to llm_models

Revision ID: add_llm_providers_fk
Revises: b5ce5d3145b5
Create Date: 2025-05-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

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
        sa.Column("is_builtin", sa.Boolean(), nullable=False, default=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # 2. Add provider_id to llm_models (nullable for now)
    op.add_column(
        "llm_models", sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True)
    )

    # 3. Migrate existing provider data
    conn = op.get_bind()
    llm_models = conn.execute(sa.text("SELECT id, provider FROM llm_models")).fetchall()
    provider_map = {}
    for row in llm_models:
        provider_name = row["provider"]
        if provider_name not in provider_map:
            # Insert provider if not exists
            provider_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO llm_providers (id, name, is_builtin, updated_at, created_at) VALUES (:id, :name, :is_builtin, now(), now())"
                ),
                {"id": provider_id, "name": provider_name, "is_builtin": True},
            )
            provider_map[provider_name] = provider_id
        # Update llm_model row with provider_id
        conn.execute(
            sa.text("UPDATE llm_models SET provider_id = :provider_id WHERE id = :model_id"),
            {"provider_id": provider_map[provider_name], "model_id": row["id"]},
        )

    # 4. Make provider_id non-nullable
    op.alter_column("llm_models", "provider_id", nullable=False)

    # 5. Add foreign key constraint
    op.create_foreign_key(
        "fk_llm_models_provider_id", "llm_models", "llm_providers", ["provider_id"], ["id"]
    )

    # 6. Drop old provider column
    op.drop_column("llm_models", "provider")


def downgrade():
    # 1. Add provider column back
    op.add_column(
        "llm_models", sa.Column("provider", sa.String(), nullable=False, server_default="unknown")
    )

    # 2. Migrate provider data back from llm_providers
    conn = op.get_bind()
    llm_models = conn.execute(sa.text("SELECT id, provider_id FROM llm_models")).fetchall()
    for row in llm_models:
        provider_id = row["provider_id"]
        provider_name = conn.execute(
            sa.text("SELECT name FROM llm_providers WHERE id = :id"), {"id": provider_id}
        ).scalar()
        conn.execute(
            sa.text("UPDATE llm_models SET provider = :provider WHERE id = :model_id"),
            {"provider": provider_name, "model_id": row["id"]},
        )

    # 3. Drop foreign key and provider_id column
    op.drop_constraint("fk_llm_models_provider_id", "llm_models", type_="foreignkey")
    op.drop_column("llm_models", "provider_id")

    # 4. Drop llm_providers table
    op.drop_table("llm_providers")
