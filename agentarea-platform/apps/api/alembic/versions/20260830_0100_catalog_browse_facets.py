"""add browse facets to registry_items

The /explore gallery filtered, sorted and counted the catalog in the browser,
over whatever pages had loaded so far. That cannot be correct: a single offset
has no meaning across per-registry fan-out, and a category whose matches sit
past the first page reads as "no results". Browsing moves into SQL, which needs
the browse dimensions as plain columns -- every registry type buries its
category somewhere different in `spec`/`tags`, and the title the UI shows is
often not `name` (skill ids carry provenance the UI strips).

`category`, `sort_key` and `featured` are derived at sync time by
agentarea_registry.application.catalog_facets.derive_facets. The backfill below
reproduces that derivation in SQL for rows that already exist; it is a one-shot
approximation for skills (it splits provenance on `--` but does not strip a
repo suffix glued on with a single dash), and the exact key is restored the
next time the registry syncs.

Revision ID: 20260830_0100_catalog_facets
Revises: 20260804_0100_drop_last_used
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_0100_catalog_facets"
down_revision: str | None = "20260804_0100_drop_last_used"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Per-type category extraction, mirroring `_category` in catalog_facets.py.
# NULLIF collapses the empty string to NULL: the client treats "" as absent, and
# a nameless facet bucket is unselectable.
_CATEGORY_SQL = {
    "bundles": "NULLIF(ri.spec->'metadata'->>'category', '')",
    "agents": "NULLIF(ri.tags->>0, '')",
    "skills": (
        "(SELECT NULLIF(substring(t.value from 10), '') "
        " FROM jsonb_array_elements_text(ri.tags) AS t(value) "
        " WHERE t.value LIKE 'category:%' LIMIT 1)"
    ),
    "mcp_servers": "NULLIF(ri.spec->'raw_spec'->'metadata'->>'agentarea:category', '')",
}

# Per-type sort key, mirroring `_title` in catalog_facets.py.
_SORT_KEY_SQL = {
    "bundles": (
        "lower(coalesce(NULLIF(ri.spec->>'display_name', ''), "
        "NULLIF(ri.spec->>'name', ''), ri.name))"
    ),
    "agents": "lower(ri.name)",
    "skills": (
        "lower(coalesce(NULLIF(ri.spec->>'display_name', ''), "
        "NULLIF(btrim(regexp_replace(split_part(ri.name, '--', 1), '[-_]+', ' ', 'g')), ''), "
        "ri.name))"
    ),
    "mcp_servers": "lower(ri.name)",
}


def upgrade() -> None:
    op.add_column("registry_items", sa.Column("category", sa.String(255), nullable=True))
    op.add_column(
        "registry_items",
        sa.Column("sort_key", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "registry_items",
        sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Featured is type-independent: a hand-curated tag on the item itself.
    op.execute("UPDATE registry_items SET featured = (tags @> '[\"featured\"]'::jsonb)")

    # Everything else depends on the owning registry's type.
    for registry_type, category_sql in _CATEGORY_SQL.items():
        op.execute(
            f"""
            UPDATE registry_items AS ri
               SET category = {category_sql},
                   sort_key = {_SORT_KEY_SQL[registry_type]}
              FROM registries AS r
             WHERE ri.registry_id = r.id
               AND r.registry_type = '{registry_type}'
            """  # noqa: S608 -- every fragment is a literal defined above
        )

    # Types with no category dimension (llm_providers, llm_models) still need a
    # usable ordering key.
    op.execute("UPDATE registry_items SET sort_key = lower(name) WHERE sort_key = ''")

    op.create_index("ix_registry_items_category", "registry_items", ["category"])
    op.create_index("ix_registry_items_sort_key", "registry_items", ["sort_key"])


def downgrade() -> None:
    op.drop_index("ix_registry_items_sort_key", table_name="registry_items")
    op.drop_index("ix_registry_items_category", table_name="registry_items")
    op.drop_column("registry_items", "featured")
    op.drop_column("registry_items", "sort_key")
    op.drop_column("registry_items", "category")
