"""Add cmd field to mcp_servers table

Revision ID: 1df4475ca99b
Revises: a453b332ab0d
Create Date: 2025-06-14 20:04:38.305245

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1df4475ca99b"
down_revision: Union[str, None] = "a453b332ab0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add cmd field to mcp_servers table
    op.add_column(
        "mcp_servers", sa.Column("cmd", postgresql.JSON(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove cmd field from mcp_servers table
    op.drop_column("mcp_servers", "cmd")
