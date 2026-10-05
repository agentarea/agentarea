"""registry_items.hosting: where an MCP connection runs

The connections gallery filters on it beside MCP / HTTP API: "vendor" for a
hosted endpoint we only call (connection_type url), "agentarea" for a
command/docker package the MCP manager runs. Derived by
catalog_facets.derive_facets on every sync; backfilled here from the spec so
the facet works before the next sync.

Revision ID: 20261005_1500_item_hosting
Revises: 20261005_1300_workspace_logo
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261005_1500_item_hosting"
down_revision: str | None = "20261005_1300_workspace_logo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("registry_items", sa.Column("hosting", sa.String(16), nullable=True))
    # Mirrors catalog_facets._hosting.
    op.execute(
        """
        UPDATE registry_items SET hosting = CASE
            WHEN spec->>'connection_type' IN ('command', 'docker') THEN 'agentarea'
            WHEN spec->>'connection_type' = 'url' THEN 'vendor'
            WHEN coalesce(spec->>'connection_type', '') = ''
                 AND (NULLIF(spec->>'url', '') IS NOT NULL
                      OR NULLIF(spec->>'remote_url', '') IS NOT NULL) THEN 'vendor'
            WHEN coalesce(spec->>'connection_type', '') = ''
                 AND (spec->'cmd' IS NOT NULL AND spec->'cmd' <> 'null'::jsonb
                      OR NULLIF(spec->>'docker_image_url', '') IS NOT NULL
                      OR NULLIF(spec->>'image', '') IS NOT NULL) THEN 'agentarea'
        END
        WHERE registry_type = 'mcp_servers'
        """
    )
    op.drop_index("ix_registry_items_browse_facets", table_name="registry_items")
    op.create_index(
        "ix_registry_items_browse_facets",
        "registry_items",
        ["registry_type", "category"],
        postgresql_include=["protocol", "hosting"],
        postgresql_where=sa.text("registry_active"),
    )


def downgrade() -> None:
    op.drop_index("ix_registry_items_browse_facets", table_name="registry_items")
    op.create_index(
        "ix_registry_items_browse_facets",
        "registry_items",
        ["registry_type", "category"],
        postgresql_include=["protocol"],
        postgresql_where=sa.text("registry_active"),
    )
    op.drop_column("registry_items", "hosting")
