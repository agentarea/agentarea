"""OpenAPI connections record the names of their secret URL variables

Some APIs carry the credential in the URL path (Telegram's
``https://api.telegram.org/bot<TOKEN>``). The base URL now holds a
``{placeholder}`` instead, the value lives in the secret manager, and this
column lists the placeholder names.

Revision ID: 20260929_1000_openapi_url_vars
Revises: 20260928_1000_inst_spec_jsonb
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_1000_openapi_url_vars"
down_revision: str | None = "20260928_1000_inst_spec_jsonb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("openapi_connections", sa.Column("url_variables", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("openapi_connections", "url_variables")
