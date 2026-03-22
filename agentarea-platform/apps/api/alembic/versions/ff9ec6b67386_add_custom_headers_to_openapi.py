"""Add custom_headers to openapi_connections.

Revision ID: ff9ec6b67386
Revises: ee8ec6b67385
Create Date: 2026-03-17

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "ff9ec6b67386"
down_revision = "ee8ec6b67385"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "openapi_connections",
        sa.Column("custom_headers", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("openapi_connections", "custom_headers")
