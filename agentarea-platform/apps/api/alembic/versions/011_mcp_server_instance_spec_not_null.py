"""make mcp server instance spec required

Revision ID: 011_mcp_instance_spec_not_null
Revises: oo1_add_workspace_invitations
Create Date: 2026-04-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "011_mcp_instance_spec_not_null"
down_revision: str | None = "oo1_add_workspace_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mcp_server_instances",
        "server_spec_id",
        existing_type=sa.String(length=255),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mcp_server_instances",
        "server_spec_id",
        existing_type=sa.String(length=255),
        nullable=True,
    )
