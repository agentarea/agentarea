"""create llm tables

Revision ID: create_llm_tables
Revises: add_sources_table
Create Date: 2024-03-XX
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

# revision identifiers, used by Alembic.
revision = "create_llm_tables"
down_revision = "add_sources_table"
branch_labels = None
depends_on = None


def upgrade():
    # Создаем таблицу llm_instances
    op.create_table(
        "llm_instance",
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

    # Создаем таблицу llm_references
    op.create_table(
        "llm_reference",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("instance_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("settings", JSON, nullable=False),
        sa.Column(
            "scope", sa.Enum("PRIVATE", "PUBLIC", name="llm_scope"), nullable=False
        ),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.text("now()")),
        sa.ForeignKeyConstraint(
            ["instance_id"], ["llm_instance.id"], ondelete="CASCADE"
        ),
    )

    # Создаем индексы
    op.create_index("ix_llm_instance_name", "llm_instance", ["name"])
    op.create_index("ix_llm_reference_name", "llm_reference", ["name"])
    op.create_index("ix_llm_reference_instance_id", "llm_reference", ["instance_id"])


def downgrade():
    # Удаляем таблицы
    op.drop_table("llm_reference")
    op.drop_table("llm_instance")

    # Удаляем enum типы
    op.execute("DROP TYPE llm_scope")
