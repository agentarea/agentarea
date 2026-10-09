"""OpenAPI connections record their last successful call

The connections page showed every OpenAPI connection as "never called": unlike
an MCP instance's ``last_dispatch``, nothing recorded a call. The column has the
same ``{"status", "at", "error"}`` shape.

Revision ID: 20261009_1200_openapi_dispatch
Revises: 20261008_1400_openapi_qparams
Create Date: 2026-10-09 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_1200_openapi_dispatch"
down_revision: str | None = "20261008_1400_openapi_qparams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("openapi_connections", sa.Column("last_dispatch", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("openapi_connections", "last_dispatch")
