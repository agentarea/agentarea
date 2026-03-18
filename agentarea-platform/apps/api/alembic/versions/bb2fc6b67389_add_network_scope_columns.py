"""add network_scope columns

Revision ID: bb2fc6b67389
Revises: aa1ec6b67387
Create Date: 2026-03-18 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "bb2fc6b67389"
down_revision: str | None = "aa1ec6b67387"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_instances",
        sa.Column("network_scope", sa.String(20), nullable=False, server_default="private"),
    )
    op.add_column(
        "skills",
        sa.Column("network_scope", sa.String(20), nullable=False, server_default="private"),
    )


def downgrade() -> None:
    op.drop_column("mcp_server_instances", "network_scope")
    op.drop_column("skills", "network_scope")
