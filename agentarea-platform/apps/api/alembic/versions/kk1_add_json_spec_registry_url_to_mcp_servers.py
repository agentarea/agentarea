"""add json_spec and registry_url to mcp_servers

Revision ID: kk1_json_spec_registry_url
Revises: 58940c431605
Create Date: 2026-04-05

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "kk1_json_spec_registry_url"
down_revision: str = "58940c431605"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("mcp_servers", sa.Column("json_spec", JSONB, nullable=True))
    op.add_column("mcp_servers", sa.Column("registry_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("mcp_servers", "registry_url")
    op.drop_column("mcp_servers", "json_spec")
