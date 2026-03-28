"""add icon to mcp_servers

Revision ID: gg1_add_icon_to_mcp_servers
Revises: ff2_add_projects_tables
Create Date: 2026-03-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "gg1_add_icon_to_mcp_servers"
down_revision: str | None = "ff2_add_projects_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_servers",
        sa.Column("icon", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("mcp_servers", "icon")
