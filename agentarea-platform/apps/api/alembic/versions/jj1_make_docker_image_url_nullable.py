"""make docker_image_url nullable for remote MCP servers

Revision ID: jj1_docker_url_nullable
Revises: ii1_remote_url_mcp
Create Date: 2026-03-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "jj1_docker_url_nullable"
down_revision: str | None = "ii1_remote_url_mcp"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "mcp_servers",
        "docker_image_url",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill empty string for any NULLs before restoring NOT NULL
    op.execute("UPDATE mcp_servers SET docker_image_url = '' WHERE docker_image_url IS NULL")
    op.alter_column(
        "mcp_servers",
        "docker_image_url",
        existing_type=sa.String(),
        nullable=False,
    )
