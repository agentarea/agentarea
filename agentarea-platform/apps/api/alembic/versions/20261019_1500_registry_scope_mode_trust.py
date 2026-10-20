"""Registries are sources with a scope, a mode and a trust level (ADR-0044)

A registry is either the platform's (every workspace sees it) or one a
workspace admin added (only that workspace sees it). ``mode`` records whether
content is copied at sync (``mirror``) or fetched on first install
(``upstream``); ``trust`` is the label every catalog card carries.
``credentials_secret_ref`` points at a workspace secret, never a copy of it.

Existing registries are the platform's: the community skill shards become
community + upstream, everything else stays official + mirror.

Items carry their registry's workspace and trust like the other copied
registry fields, so browse stays on one table. Only items their source still
publishes are backfilled: the rest are hidden, and the first sync deletes them
or, for the few an install keeps, gives them their registry's trust. The two
count indexes gain the workspace column in the next revision, concurrently.

Every statement here waits at most ``lock_timeout`` for its lock: a migration
queued behind an open transaction would otherwise queue every catalog read
behind itself.

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
# Items take the server default, official; only the other registries' items
# change. One statement per registry, each served by an index on the item's
# registry (for an active one, the partial browse indexes over live rows), so
# the 1.2 GB table is not scanned whole under ACCESS EXCLUSIVE.
TRUST_REGISTRIES = (
    "SELECT id AS registry_id, trust, registry_type, is_active AS active "
    "FROM registries WHERE trust <> 'official'"
)
BACKFILL_ITEM_TRUST = (
    "UPDATE registry_items SET registry_trust = :trust "
    "WHERE registry_id = :registry_id AND registry_type = :registry_type AND in_source "
    "AND (registry_active OR NOT :active) AND registry_trust IS DISTINCT FROM :trust"
)
LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
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
    bind = op.get_bind()
    for registry in bind.execute(sa.text(TRUST_REGISTRIES)).mappings().all():
        bind.execute(sa.text(BACKFILL_ITEM_TRUST), dict(registry))


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
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
