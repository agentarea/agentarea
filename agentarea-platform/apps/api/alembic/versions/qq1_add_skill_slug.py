"""add workspace-scoped slug to skills + provenance unique for catalog skills

Mirrors ``pp1_add_agent_mcp_slugs`` for the ``skills`` table:
  - immutable, human-readable ``slug`` backfilled from ``name`` with
    workspace-scoped collision handling, then flipped to NOT NULL;
  - ``UNIQUE(workspace_id, slug)`` — the identity contract for all skills.

Additionally adds a partial unique index on ``registry_item_id`` so that
catalog skills reconciled by the operator are deduplicated by provenance
(one skill per registry item), race-proof under overlapping reconciles.
User skills keep ``registry_item_id IS NULL`` and are unaffected.

NOTE: existing duplicate catalog skills must be removed before this migration
runs (the slug backfill caps at 999 collisions per name, and both unique
indexes reject pre-existing duplicates). Dedup of pre-existing rows is done
manually; this migration only touches schema + slug values.

Revision ID: qq1_add_skill_slug
Revises: pp1_add_agent_mcp_slugs
Create Date: 2026-05-31
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "qq1_add_skill_slug"
down_revision: str | None = "pp1_add_agent_mcp_slugs"
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


def _backfill_slugs(connection: sa.engine.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, workspace_id, name FROM skills ORDER BY created_at")
    ).fetchall()

    taken_per_workspace: dict[str, set[str]] = {}
    update_stmt = sa.text("UPDATE skills SET slug = :slug WHERE id = :id")

    for row in rows:
        row_id = row[0]
        workspace_id = row[1] or ""
        name = row[2] or ""
        base = _generate_slug(name)
        slug = _dedupe_within_workspace(base, taken_per_workspace, workspace_id)
        connection.execute(update_stmt, {"slug": slug, "id": row_id})


def upgrade() -> None:
    # 1. Add nullable slug so the backfill can populate it.
    op.add_column("skills", sa.Column("slug", sa.String(120), nullable=True))

    # 2. Backfill from name, workspace-scoped collision handling.
    _backfill_slugs(op.get_bind())

    # 3. Flip to NOT NULL now that every row has a value.
    op.alter_column("skills", "slug", existing_type=sa.String(120), nullable=False)

    # 4. Slug lookup index + workspace-scoped uniqueness (identity contract).
    op.create_index("ix_skills_slug", "skills", ["slug"])
    op.create_unique_constraint("uq_skills_workspace_slug", "skills", ["workspace_id", "slug"])

    # 5. Provenance uniqueness for catalog skills only (operator dedup target).
    op.create_index(
        "uq_skills_registry_item",
        "skills",
        ["registry_item_id"],
        unique=True,
        postgresql_where=sa.text("registry_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_skills_registry_item", table_name="skills")
    op.drop_constraint("uq_skills_workspace_slug", "skills", type_="unique")
    op.drop_index("ix_skills_slug", table_name="skills")
    op.drop_column("skills", "slug")
