"""Registries are sources with a scope, a mode and a trust level (ADR-0044)

A registry is either the platform's (every workspace sees it) or one a
workspace admin added (only that workspace sees it). ``mode`` records whether
content is copied at sync (``mirror``) or fetched on first install
(``upstream``); ``trust`` is the label every catalog card carries.
``credentials_secret_ref`` points at a workspace secret, never a copy of it.

Existing registries are the platform's: the community skill shards become
community + upstream, everything else stays official + mirror.

Items carry their registry's workspace and trust like the other copied
registry fields, so browse stays on one table. The two indexes that answer
totals and facets from the index alone include the workspace column, so the
visibility filter does not send them to the heap.

Registry names are unique per scope: the platform's by name, a workspace's
within that workspace.

Revision ID: 20261019_1500_registry_scope
Revises: 20261019_1200_catalog_snapshot
Create Date: 2026-10-19 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "20261019_1500_registry_scope"
down_revision: str | None = "20261019_1200_catalog_snapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Idempotent, so the schema-backed test runs them on rows it writes itself.
BACKFILL_REGISTRIES = (
    "UPDATE registries SET mode = 'upstream', trust = 'community' "
    "WHERE scope = 'platform' AND name LIKE 'system-skills-community-%'"
)
BACKFILL_ITEM_TRUST = (
    "UPDATE registry_items ri SET registry_trust = r.trust FROM registries r "
    "WHERE r.id = ri.registry_id AND ri.registry_trust IS DISTINCT FROM r.trust"
)


_COUNT_INDEXES = {
    "ix_registry_items_browse_name": (["registry_type", "sort_key", "id"], []),
    "ix_registry_items_browse_facets": (
        ["registry_type", "category"],
        ["protocol", "hosting", "pricing"],
    ),
}


def _recreate_count_indexes(*, with_workspace: bool) -> None:
    # Built beside the old one and swapped, all concurrently: a plain DROP or
    # CREATE INDEX holds a lock every catalog read queues behind.
    with op.get_context().autocommit_block():
        for name, (columns, include) in _COUNT_INDEXES.items():
            # What an interrupted earlier run left behind, invalid.
            op.drop_index(
                f"{name}_next",
                table_name="registry_items",
                postgresql_concurrently=True,
                if_exists=True,
            )
            op.create_index(
                f"{name}_next",
                "registry_items",
                columns,
                postgresql_include=[
                    *include,
                    *(["registry_workspace_id"] if with_workspace else []),
                ],
                postgresql_where=sa.text("registry_active"),
                postgresql_concurrently=True,
            )
            op.drop_index(name, table_name="registry_items", postgresql_concurrently=True)
            op.execute(f"ALTER INDEX {name}_next RENAME TO {name}")


def upgrade() -> None:
    op.add_column(
        "registries",
        sa.Column("scope", sa.String(16), nullable=False, server_default="platform"),
    )
    op.add_column("registries", sa.Column("workspace_id", sa.String(255), nullable=True))
    op.add_column(
        "registries", sa.Column("mode", sa.String(16), nullable=False, server_default="mirror")
    )
    op.add_column(
        "registries",
        sa.Column("trust", sa.String(16), nullable=False, server_default="official"),
    )
    op.add_column(
        "registries",
        sa.Column(
            "credentials_secret_ref",
            UUID(as_uuid=True),
            sa.ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    op.add_column("registries", sa.Column("source_ref", sa.String(255), nullable=True))
    op.add_column("registries", sa.Column("source_path", sa.Text(), nullable=True))
    op.execute(BACKFILL_REGISTRIES)

    op.create_check_constraint(
        "ck_registries_scope", "registries", "scope IN ('platform', 'workspace')"
    )
    op.create_check_constraint("ck_registries_mode", "registries", "mode IN ('mirror', 'upstream')")
    op.create_check_constraint(
        "ck_registries_trust",
        "registries",
        "trust IN ('official', 'verified', 'community', 'private')",
    )
    # A workspace registry holds only catalog-only types: a sync of any other
    # type materializes platform-wide entities (MCP specs, model specs).
    op.create_check_constraint(
        "ck_registries_scope_workspace",
        "registries",
        "(scope = 'platform' AND workspace_id IS NULL) OR "
        "(scope = 'workspace' AND workspace_id IS NOT NULL "
        "AND registry_type IN ('skills', 'agents'))",
    )
    op.create_index("ix_registries_workspace_id", "registries", ["workspace_id"])

    op.drop_constraint("uq_registries_name", "registries", type_="unique")
    op.create_index(
        "uq_registries_platform_name",
        "registries",
        ["name"],
        unique=True,
        postgresql_where=sa.text("scope = 'platform'"),
    )
    op.create_index(
        "uq_registries_workspace_name",
        "registries",
        ["workspace_id", "name"],
        unique=True,
        postgresql_where=sa.text("scope = 'workspace'"),
    )

    op.add_column(
        "registry_items", sa.Column("registry_workspace_id", sa.String(255), nullable=True)
    )
    op.add_column(
        "registry_items",
        sa.Column("registry_trust", sa.String(16), nullable=False, server_default="official"),
    )
    op.execute(BACKFILL_ITEM_TRUST)
    _recreate_count_indexes(with_workspace=True)


def downgrade() -> None:
    _recreate_count_indexes(with_workspace=False)
    op.drop_column("registry_items", "registry_trust")
    op.drop_column("registry_items", "registry_workspace_id")

    op.execute("DELETE FROM registries WHERE scope = 'workspace'")
    op.drop_index("uq_registries_workspace_name", table_name="registries")
    op.drop_index("uq_registries_platform_name", table_name="registries")
    op.create_unique_constraint("uq_registries_name", "registries", ["name"])
    op.drop_index("ix_registries_workspace_id", table_name="registries")
    for name in ("scope_workspace", "trust", "mode", "scope"):
        op.drop_constraint(f"ck_registries_{name}", "registries", type_="check")
    for column in (
        "source_path",
        "source_ref",
        "credentials_secret_ref",
        "trust",
        "mode",
        "workspace_id",
        "scope",
    ):
        op.drop_column("registries", column)
