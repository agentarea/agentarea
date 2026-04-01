"""add remote_url to mcp_servers

Revision ID: ii1_remote_url_mcp
Revises: hh1_enrich_model_specs
Create Date: 2026-03-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ii1_remote_url_mcp"
down_revision: str | None = "hh1_enrich_model_specs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("remote_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_servers", "remote_url")
