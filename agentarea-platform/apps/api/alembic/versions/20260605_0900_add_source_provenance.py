"""Add explicit source provenance; retire the workspace_id='system' marker

Replaces the magic ``workspace_id == 'system'`` sentinel with:
- a real ``platform`` workspace row (+ ``platform`` bootstrap principal), and
- an explicit ``source`` provenance column on the four user-owned resource
  tables (agents, skills, mcp_server_instances, provider_configs).

Backfill is one-way: rows previously marked with ``workspace_id='system'`` get
``source='official'`` and are then re-homed to the ``platform`` workspace. The
downgrade only drops the new columns; it does NOT restore the 'system' strings
(the original marker is unrecoverable once rewritten).

Revision ID: 20260605_0900_source_provenance
Revises: 20260604_1300_workspaces_table
Create Date: 2026-06-05 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260605_0900_source_provenance"
down_revision: str = "20260604_1300_workspaces_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that gain a `source` column.
SOURCE_TABLES = ("agents", "skills", "mcp_server_instances", "provider_configs")

# Every seeded table that historically used workspace_id='system'.
SYSTEM_MARKED_TABLES = (
    "agents",
    "skills",
    "mcp_server_instances",
    "provider_configs",
    "provider_specs",
    "model_specs",
    "model_instances",
    "mcp_servers",
    "registries",
    "registry_items",
)


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Seed the platform workspace row (idempotent).
    conn.execute(
        sa.text(
            "INSERT INTO workspaces (id, type, name, owner_user_id, created_at, updated_at) "
            "VALUES ('platform', 'platform', 'Platform', 'platform', now(), now()) "
            "ON CONFLICT (id) DO NOTHING"
        )
    )

    # 2. Add the `source` column (server_default for existing rows).
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

    # 3. Backfill provenance BEFORE the workspace_id is rewritten — the 'system'
    #    marker must still be present here.
    # Table names come from the hardcoded SOURCE_TABLES tuple, not user input.
    for table in SOURCE_TABLES:
        stmt = f"UPDATE {table} SET source = 'official' WHERE workspace_id = 'system'"  # noqa: S608
        conn.execute(sa.text(stmt))

    # 4. Purge the magic string: re-home seeded rows onto the real platform
    #    workspace and principal. created_by exists on every WorkspaceScoped
    #    table; mcp_servers uses AuditMixin (nullable created_by) but the column
    #    is still present, so the UPDATE is uniform.
    # Table names come from the hardcoded SYSTEM_MARKED_TABLES tuple, not user input.
    for table in SYSTEM_MARKED_TABLES:
        stmt = (
            f"UPDATE {table} SET workspace_id = 'platform', created_by = 'platform' "  # noqa: S608
            "WHERE workspace_id = 'system'"
        )
        conn.execute(sa.text(stmt))

    # 5. Drop the server_default so the application-level default governs new rows.
    for table in SOURCE_TABLES:
        op.alter_column(table, "source", server_default=None)


def downgrade() -> None:
    # One-way data migration: the original 'system' workspace markers are not
    # restored (they are unrecoverable once rewritten). Only the columns added
    # by this revision are dropped.
    for table in SOURCE_TABLES:
        op.drop_column(table, "source")
