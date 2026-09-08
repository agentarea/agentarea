"""Link workspace OpenAPI connections to trusted catalog templates.

Revision ID: 20260907_1300_openapi_registry
Revises: 20260902_1000_drop_client_src
Create Date: 2026-09-07 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "20260907_1300_openapi_registry"
down_revision: str | None = "20260902_1000_drop_client_src"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "openapi_connections",
        sa.Column("registry_item_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "openapi_connections",
        sa.Column("allowed_auth_origins", sa.JSON(), nullable=True),
    )
    op.create_foreign_key(
        "openapi_connections_registry_item_id_fkey",
        "openapi_connections",
        "registry_items",
        ["registry_item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_openapi_connections_registry_item_id",
        "openapi_connections",
        ["registry_item_id"],
    )
    op.create_unique_constraint(
        "uq_openapi_conn_workspace_registry",
        "openapi_connections",
        ["workspace_id", "registry_item_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_openapi_conn_workspace_registry",
        "openapi_connections",
        type_="unique",
    )
    op.drop_index(
        "ix_openapi_connections_registry_item_id",
        table_name="openapi_connections",
    )
    op.drop_constraint(
        "openapi_connections_registry_item_id_fkey",
        "openapi_connections",
        type_="foreignkey",
    )
    op.drop_column("openapi_connections", "registry_item_id")
    op.drop_column("openapi_connections", "allowed_auth_origins")
