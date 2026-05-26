"""add workspace-scoped slugs to agents and mcp_servers

Adds an immutable, human-readable `slug` to both ``agents`` and
``mcp_servers``. Backfills existing rows from ``name`` using the same
algorithm as :mod:`agentarea_common.utils.slug` (inlined here so this
migration stays self-contained — migrations should never import from
domain libraries that may evolve under them).

Revision ID: pp1_add_agent_mcp_slugs
Revises: oo1_add_workspace_invitations
Create Date: 2026-05-27
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "pp1_add_agent_mcp_slugs"
down_revision: str | None = "oo1_add_workspace_invitations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Self-contained slug helper (kept in sync with
# agentarea_common.utils.slug.generate_slug). Inlined so the migration is
# safe to run against future code revisions.
# ---------------------------------------------------------------------------

_MAX_SLUG_LENGTH = 100
_FALLBACK_SLUG = "item"


def _generate_slug(name: str) -> str:
    if name is None:
        name = ""
    if not isinstance(name, str):
        name = str(name)
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    if len(slug) > _MAX_SLUG_LENGTH:
        slug = slug[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug or _FALLBACK_SLUG


def _dedupe_within_workspace(
    base: str, taken_per_workspace: dict[str, set[str]], workspace_id: str
) -> str:
    """Return a workspace-unique slug, registering it in the per-workspace set."""
    taken = taken_per_workspace.setdefault(workspace_id, set())
    if base not in taken:
        taken.add(base)
        return base
    for suffix in range(2, 1000):
        candidate = f"{base}-{suffix}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise RuntimeError(
        f"Cannot derive a unique slug for workspace {workspace_id!r}: "
        f"base '{base}' has more than 999 collisions"
    )


def _backfill_slugs(connection: sa.engine.Connection, table_name: str) -> None:
    """Compute and assign slugs for every existing row of ``table_name``."""
    rows = connection.execute(
        sa.text(f"SELECT id, workspace_id, name FROM {table_name}")
    ).fetchall()

    taken_per_workspace: dict[str, set[str]] = {}
    update_stmt = sa.text(f"UPDATE {table_name} SET slug = :slug WHERE id = :id")

    for row in rows:
        row_id = row[0]
        workspace_id = row[1] or ""
        name = row[2] or ""
        base = _generate_slug(name)
        slug = _dedupe_within_workspace(base, taken_per_workspace, workspace_id)
        connection.execute(update_stmt, {"slug": slug, "id": row_id})


def upgrade() -> None:
    # 1. Add nullable slug columns so the backfill can populate them.
    op.add_column("agents", sa.Column("slug", sa.String(120), nullable=True))
    op.add_column("mcp_servers", sa.Column("slug", sa.String(120), nullable=True))

    # 2. Backfill from name, workspace-scoped collision handling.
    bind = op.get_bind()
    _backfill_slugs(bind, "agents")
    _backfill_slugs(bind, "mcp_servers")

    # 3. Flip to NOT NULL now that every row has a value.
    op.alter_column("agents", "slug", existing_type=sa.String(120), nullable=False)
    op.alter_column("mcp_servers", "slug", existing_type=sa.String(120), nullable=False)

    # 4. Indexes for slug lookups.
    op.create_index("ix_agents_slug", "agents", ["slug"])
    op.create_index("ix_mcp_servers_slug", "mcp_servers", ["slug"])

    # 5. Workspace-scoped uniqueness — the actual contract.
    op.create_unique_constraint(
        "uq_agents_workspace_slug", "agents", ["workspace_id", "slug"]
    )
    op.create_unique_constraint(
        "uq_mcp_servers_workspace_slug", "mcp_servers", ["workspace_id", "slug"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_mcp_servers_workspace_slug", "mcp_servers", type_="unique")
    op.drop_constraint("uq_agents_workspace_slug", "agents", type_="unique")
    op.drop_index("ix_mcp_servers_slug", table_name="mcp_servers")
    op.drop_index("ix_agents_slug", table_name="agents")
    op.drop_column("mcp_servers", "slug")
    op.drop_column("agents", "slug")
