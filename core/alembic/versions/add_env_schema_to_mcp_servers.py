"""Add env_schema field to mcp_servers table

Revision ID: add_env_schema_mcp
Revises: 8954caa2c0f6
Create Date: 2025-06-06 11:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "add_env_schema_mcp"
down_revision: Union[str, None] = "b5ce5d3145b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add env_schema field to mcp_servers table."""
    # Add env_schema column to mcp_servers table
    op.add_column(
        "mcp_servers",
        sa.Column("env_schema", postgresql.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    """Remove env_schema field from mcp_servers table."""
    # Remove env_schema column from mcp_servers table
    op.drop_column("mcp_servers", "env_schema")
