"""initial migration

Revision ID: initial_migration
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "initial_migration"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "module_specs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column(
            "input_format", postgresql.JSON(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "output_format", postgresql.JSON(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.Column("tags", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("environment", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("license", sa.String(), nullable=True),
        sa.Column("model_framework", sa.String(), nullable=True),
        sa.Column("memory_requirements", sa.String(), nullable=True),
        sa.Column("gpu_requirements", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_module_specs_module_id"), "module_specs", ["module_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_module_specs_module_id"), table_name="module_specs")
    op.drop_table("module_specs")
