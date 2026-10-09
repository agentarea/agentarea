"""An auth config minted by a connect flow is deleted with its connection or instance

Catalog OAuth and MCP OAuth connects create one auth config per connection or
instance, and point the owner at it only once the provider calls back. Nothing
tied the config to its owner, so deleting the owner -- or abandoning the connect
-- left the config and its credential behind. Each config now names the
connection or instance it was minted for, and goes with it (ON DELETE CASCADE).
A config an admin created to share names neither.

The backfill recognises a minted config by what the connect flows write: a
``credential_mode`` in its config and a name ending in the first eight hex
digits of its owner's id (``mcp-oauth-<instance>``, ``<provider>-<connection>``),
matched within the workspace and only when exactly one owner fits.

Revision ID: 20261009_1700_auth_config_owner
Revises: 20261009_1210_openapi_qp_tools
Create Date: 2026-10-09 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_1700_auth_config_owner"
down_revision: str | None = "20261009_1210_openapi_qp_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL = [
    """
    UPDATE mcp_auth_configs a SET mcp_instance_id = i.id
    FROM mcp_server_instances i
    WHERE a.openapi_connection_id IS NULL AND a.mcp_instance_id IS NULL
      AND a.config ->> 'credential_mode' IS NOT NULL
      AND i.workspace_id = a.workspace_id
      AND a.name = 'mcp-oauth-' || left(i.id::text, 8)
      AND (
        SELECT count(*) FROM mcp_server_instances o
        WHERE o.workspace_id = a.workspace_id AND a.name = 'mcp-oauth-' || left(o.id::text, 8)
      ) = 1
    """,
    """
    UPDATE mcp_auth_configs a SET openapi_connection_id = c.id
    FROM openapi_connections c
    WHERE a.openapi_connection_id IS NULL AND a.mcp_instance_id IS NULL
      AND a.config ->> 'credential_mode' IS NOT NULL
      AND c.workspace_id = a.workspace_id
      AND a.name = (a.config ->> 'provider') || '-' || left(c.id::text, 8)
      AND (
        SELECT count(*) FROM openapi_connections o
        WHERE o.workspace_id = a.workspace_id
          AND a.name = (a.config ->> 'provider') || '-' || left(o.id::text, 8)
      ) = 1
    """,
]


def upgrade() -> None:
    op.add_column(
        "mcp_auth_configs",
        sa.Column("openapi_connection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "mcp_auth_configs",
        sa.Column("mcp_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "mcp_auth_configs_openapi_connection_id_fkey",
        "mcp_auth_configs",
        "openapi_connections",
        ["openapi_connection_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "mcp_auth_configs_mcp_instance_id_fkey",
        "mcp_auth_configs",
        "mcp_server_instances",
        ["mcp_instance_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_mcp_auth_configs_openapi_connection_id",
        "mcp_auth_configs",
        ["openapi_connection_id"],
    )
    op.create_index("ix_mcp_auth_configs_mcp_instance_id", "mcp_auth_configs", ["mcp_instance_id"])
    op.create_check_constraint(
        "ck_mcp_auth_configs_one_owner",
        "mcp_auth_configs",
        "openapi_connection_id IS NULL OR mcp_instance_id IS NULL",
    )
    for statement in BACKFILL:
        op.execute(statement)


def downgrade() -> None:
    op.drop_constraint("ck_mcp_auth_configs_one_owner", "mcp_auth_configs", type_="check")
    op.drop_index("ix_mcp_auth_configs_mcp_instance_id", table_name="mcp_auth_configs")
    op.drop_index("ix_mcp_auth_configs_openapi_connection_id", table_name="mcp_auth_configs")
    op.drop_constraint(
        "mcp_auth_configs_mcp_instance_id_fkey", "mcp_auth_configs", type_="foreignkey"
    )
    op.drop_constraint(
        "mcp_auth_configs_openapi_connection_id_fkey", "mcp_auth_configs", type_="foreignkey"
    )
    op.drop_column("mcp_auth_configs", "mcp_instance_id")
    op.drop_column("mcp_auth_configs", "openapi_connection_id")
