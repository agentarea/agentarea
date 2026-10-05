"""workspaces.logo_key: the object key of the workspace logo, NULL for none

Revision ID: 20261005_1300_workspace_logo
Revises: 20261005_1200_mcp_inst_transport
Create Date: 2026-10-05 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_1300_workspace_logo"
down_revision: str | None = "20261005_1200_mcp_inst_transport"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("logo_key", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "logo_key")
