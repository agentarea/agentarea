"""Allow multiple connection instances from one catalog item.

Revision ID: 20260908_1000_multi_catalog_conn
Revises: 20260907_1300_openapi_registry
Create Date: 2026-09-08 10:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260908_1000_multi_catalog_conn"
down_revision: str | None = "20260907_1300_openapi_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # registry_item_id identifies the reusable catalog definition. It must not
    # make that definition a singleton within a workspace.
    op.drop_constraint(
        "uq_openapi_conn_workspace_registry",
        "openapi_connections",
        type_="unique",
    )


def downgrade() -> None:
    # Downgrade is intentionally strict: if a workspace created multiple
    # instances, PostgreSQL will refuse to discard that valid data implicitly.
    op.create_unique_constraint(
        "uq_openapi_conn_workspace_registry",
        "openapi_connections",
        ["workspace_id", "registry_item_id"],
    )
