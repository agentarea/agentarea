"""Globalize registry catalog; add source provenance to mcp_servers/model_specs

Two coupled changes that retire the magic 'platform' workspace as a visibility
sentinel for built-in content:

1. Registry tables (``registries``, ``registry_items``) become GLOBAL catalog
   infrastructure: drop their ``workspace_id`` and ``created_by`` columns. All
   existing rows were platform-owned, so the data is simply dropped. The
   downgrade re-adds the columns as nullable (the original values are not
   restored).

2. Built-in visibility for ``mcp_servers`` and ``model_specs`` moves from the
   workspace filter to an explicit ``source`` provenance column (matching the
   pattern already used by agents/skills/mcp_server_instances/provider_configs).
   Rows currently homed in the ``platform`` workspace are backfilled to
   ``source='official'`` so they remain globally visible without the
   ``accessible_workspaces=[ws, 'platform']`` hack.

Revision ID: 20260608_1000_globalize_registry
Revises: 20260607_0001_merge_heads
Create Date: 2026-06-08 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260608_1000_globalize_registry"
down_revision: str = "20260607_0001_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that gain a `source` provenance column in this revision.
SOURCE_TABLES = ("mcp_servers", "model_specs")

# Registry tables that lose their workspace scoping (become global catalog infra).
GLOBAL_REGISTRY_TABLES = ("registries", "registry_items")


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Add `source` provenance to the two seeded tables that lacked it.
    for table in SOURCE_TABLES:
        op.add_column(
            table,
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="workspace_custom",
            ),
        )

    # 2. Backfill provenance: rows seeded into the platform workspace are
    #    official/built-in. Table names come from the hardcoded SOURCE_TABLES
    #    tuple, not user input.
    for table in SOURCE_TABLES:
        stmt = f"UPDATE {table} SET source = 'official' WHERE workspace_id = 'platform'"  # noqa: S608
        conn.execute(sa.text(stmt))

    # 3. Drop the server_default so the application-level default governs new rows.
    for table in SOURCE_TABLES:
        op.alter_column(table, "source", server_default=None)

    # 4. Globalize the registry catalog: drop workspace scoping columns.
    for table in GLOBAL_REGISTRY_TABLES:
        op.drop_column(table, "created_by")
        op.drop_column(table, "workspace_id")


def downgrade() -> None:
    # Re-add registry workspace columns as nullable (original values are not
    # restored — the catalog is global now and the data was dropped).
    for table in GLOBAL_REGISTRY_TABLES:
        op.add_column(
            table,
            sa.Column("workspace_id", sa.String(length=255), nullable=True),
        )
        op.add_column(
            table,
            sa.Column("created_by", sa.String(length=255), nullable=True),
        )

    for table in SOURCE_TABLES:
        op.drop_column(table, "source")
