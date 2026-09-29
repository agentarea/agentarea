"""serve catalog browsing from indexes; one registry per name

/explore ordered by `registries.recommendation_priority` through a join, so no
index on `registry_items` could produce the page order: every page, total and
facet count was a seq scan of the whole table. On RU prod that table is 1.4 GB
(~300k rows, ~1 KB of spec each); a skills page cost ~12 s against the
webapp's 8 s budget, and the scans starved every other query of IO.

1. Registries are made unique by name. Reconcile looks sources up by name,
   and two writers racing on a first sync each created one -- prod carried a
   second copy of most skill shards and of the MCP catalog. The most recently
   synced copy is kept; anything pointing at an item of a stale copy is moved to
   the kept copy's item with the same external_id before the stale copy (and,
   by cascade, its items) is deleted.
2. Each item gets its registry's type, weight and active flag
   (`registry_type`, `registry_priority`, `registry_active`) plus its derived
   `protocol`, so browse filters and orders on one table.
3. Browse indexes matching each sort and a covering index for totals/facets,
   all partial on active registries, plus trigram indexes for `ILIKE '%term%'`
   search. They supersede the single-column category and sort_key indexes.

Revision ID: 20260925_1800_catalog_browse
Revises: 20260926_1000_membership_rows
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_1800_catalog_browse"
down_revision: str | None = "20260926_1000_membership_rows"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BROWSE_INDEXES: dict[str, list[str]] = {
    "ix_registry_items_browse_recommended": [
        "registry_type",
        "featured DESC",
        "registry_priority",
        "recommendation_rank",
        "sort_key",
        "id",
    ],
    "ix_registry_items_browse_category_recommended": [
        "registry_type",
        "category",
        "featured DESC",
        "registry_priority",
        "recommendation_rank",
        "sort_key",
        "id",
    ],
    "ix_registry_items_browse_name": ["registry_type", "sort_key", "id"],
    "ix_registry_items_browse_category_name": ["registry_type", "category", "sort_key", "id"],
}


def _merge_duplicate_registries() -> None:
    op.execute(
        """
        CREATE TEMP TABLE _registry_moves ON COMMIT DROP AS
        WITH ranked AS (
            SELECT id, name,
                   row_number() OVER (
                       PARTITION BY name
                       ORDER BY last_synced_at DESC NULLS LAST, created_at DESC, id
                   ) AS rn
            FROM registries
        )
        SELECT stale.id AS stale_id, kept.id AS kept_id
        FROM ranked stale
        JOIN ranked kept ON kept.name = stale.name AND kept.rn = 1
        WHERE stale.rn > 1
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _registry_item_moves ON COMMIT DROP AS
        SELECT old_item.id AS old_id, new_item.id AS new_id
        FROM _registry_moves m
        JOIN registry_items old_item ON old_item.registry_id = m.stale_id
        JOIN registry_items new_item
          ON new_item.registry_id = m.kept_id AND new_item.external_id = old_item.external_id
        """
    )
    # A workspace holds at most one fork and one install per catalog item. Where
    # it already has one for the kept item, the stale reference is left as is:
    # the fork keeps working as a plain tenant skill, and the install row goes
    # with the stale item.
    op.execute(
        """
        UPDATE skills s SET registry_item_id = m.new_id
        FROM _registry_item_moves m
        WHERE s.registry_item_id = m.old_id
          AND NOT EXISTS (
              SELECT 1 FROM skills other
              WHERE other.workspace_id = s.workspace_id AND other.registry_item_id = m.new_id
          )
        """
    )
    op.execute(
        """
        UPDATE registry_item_installs x SET registry_item_id = m.new_id
        FROM _registry_item_moves m
        WHERE x.registry_item_id = m.old_id
          AND NOT EXISTS (
              SELECT 1 FROM registry_item_installs other
              WHERE other.workspace_id = x.workspace_id AND other.registry_item_id = m.new_id
          )
        """
    )
    op.execute(
        """
        UPDATE mcp_servers t SET registry_item_id = m.new_id
        FROM _registry_item_moves m WHERE t.registry_item_id = m.old_id
        """
    )
    op.execute(
        """
        UPDATE openapi_connections t SET registry_item_id = m.new_id
        FROM _registry_item_moves m WHERE t.registry_item_id = m.old_id
        """
    )
    op.execute(
        """
        UPDATE agents t SET registry_item_id = m.new_id::text
        FROM _registry_item_moves m WHERE t.registry_item_id = m.old_id::text
        """
    )
    op.execute("DELETE FROM registries WHERE id IN (SELECT stale_id FROM _registry_moves)")


def upgrade() -> None:
    _merge_duplicate_registries()
    op.create_unique_constraint("uq_registries_name", "registries", ["name"])

    op.add_column("registry_items", sa.Column("registry_type", sa.String(50), nullable=True))
    op.add_column("registry_items", sa.Column("registry_priority", sa.Integer(), nullable=True))
    op.add_column("registry_items", sa.Column("registry_active", sa.Boolean(), nullable=True))
    op.add_column("registry_items", sa.Column("protocol", sa.String(10), nullable=True))
    # Mirrors catalog_facets._protocol: only connections have a protocol, and a
    # connection that never recorded a connection_type is an MCP server.
    op.execute(
        """
        UPDATE registry_items i
        SET registry_type = r.registry_type,
            registry_priority = r.recommendation_priority,
            registry_active = r.is_active,
            protocol = CASE
                WHEN r.registry_type <> 'mcp_servers' THEN NULL
                WHEN i.spec->>'connection_type' = 'openapi' THEN 'api'
                ELSE 'mcp'
            END
        FROM registries r
        WHERE r.id = i.registry_id
        """
    )
    op.alter_column("registry_items", "registry_type", nullable=False)
    op.alter_column("registry_items", "registry_priority", nullable=False)
    op.alter_column("registry_items", "registry_active", nullable=False)

    op.drop_index("ix_registry_items_category", table_name="registry_items")
    op.drop_index("ix_registry_items_sort_key", table_name="registry_items")
    for name, columns in _BROWSE_INDEXES.items():
        op.create_index(
            name,
            "registry_items",
            [sa.text(c) for c in columns],
            postgresql_where=sa.text("registry_active"),
        )
    op.create_index(
        "ix_registry_items_browse_facets",
        "registry_items",
        ["registry_type", "category"],
        postgresql_include=["protocol"],
        postgresql_where=sa.text("registry_active"),
    )

    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in ("name", "description"):
        op.create_index(
            f"ix_registry_items_{column}_trgm",
            "registry_items",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )


def downgrade() -> None:
    # One-way for the merged duplicates: the stale copies are not restored.
    for column in ("name", "description"):
        op.drop_index(f"ix_registry_items_{column}_trgm", table_name="registry_items")
    op.drop_index("ix_registry_items_browse_facets", table_name="registry_items")
    for name in _BROWSE_INDEXES:
        op.drop_index(name, table_name="registry_items")
    op.create_index("ix_registry_items_sort_key", "registry_items", ["sort_key"])
    op.create_index("ix_registry_items_category", "registry_items", ["category"])

    op.drop_column("registry_items", "protocol")
    op.drop_column("registry_items", "registry_active")
    op.drop_column("registry_items", "registry_priority")
    op.drop_column("registry_items", "registry_type")
    op.drop_constraint("uq_registries_name", "registries", type_="unique")
