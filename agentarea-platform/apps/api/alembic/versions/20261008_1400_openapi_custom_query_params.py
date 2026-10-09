"""OpenAPI connections carry query parameters sent with every request

Some APIs take their key in the query string (``?api_key=``, Yandex Metrica's
``?ms=``). Each entry mirrors ``custom_headers``: ``{"name", "secret", "value"}``,
with secret values kept in the secret manager rather than this row.

Revision ID: 20261008_1400_openapi_qparams
Revises: 20261006_0920_webhook_backfill
Create Date: 2026-10-08 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261008_1400_openapi_qparams"
down_revision: str | None = "20261006_0920_webhook_backfill"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("openapi_connections", sa.Column("custom_query_params", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("openapi_connections", "custom_query_params")
