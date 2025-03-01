"""create model tables

Revision ID: create_model_tables
Revises: create_tool_tables
Create Date: 2025-03-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

# revision identifiers, used by Alembic.
revision = "create_model_tables"
down_revision = "add_sources_table"
branch_labels = None
depends_on = None


def upgrade():
    # Создаем таблицу model_instances
    op.create_table(
        "model_instance",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String()),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
    )

    # Создаем таблицу model_references
    op.create_table(
        "model_reference",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("instance_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("settings", JSON, nullable=False),
        sa.Column(
            "scope", sa.Enum("PRIVATE", "PUBLIC", name="model_scope"), nullable=False
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["model_instance.id"], ondelete="CASCADE"
        ),
    )

    # Создаем индексы
    op.create_index("ix_model_instance_name", "model_instance", ["name"])
    op.create_index("ix_model_reference_name", "model_reference", ["name"])
    op.create_index(
        "ix_model_reference_instance_id", "model_reference", ["instance_id"]
    )


def downgrade():
    # Удаляем таблицы
    op.drop_table("model_reference")
    op.drop_table("model_instance")

    # Удаляем enum типы
    op.execute("DROP TYPE model_scope")
