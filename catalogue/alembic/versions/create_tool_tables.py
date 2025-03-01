"""create tool tables

Revision ID: create_tool_tables
Revises: create_model_tables
Create Date: 2025-03-01

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic
revision = "create_tool_tables"
down_revision = "create_model_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create base tools table
    op.create_table(
        "tool",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_tool_name"), "tool", ["name"], unique=True)

    # Create MCP tools table
    op.create_table(
        "mcp_tools",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("image", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["id"], ["tool.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("mcp_tools")
    op.drop_index(op.f("ix_tool_name"), table_name="tool")
    op.drop_table("tool")
