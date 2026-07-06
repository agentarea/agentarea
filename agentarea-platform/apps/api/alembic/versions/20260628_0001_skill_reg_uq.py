"""scope skills registry-item uniqueness to workspace + drop retired platform skills

Two coupled fixes for catalog-skill install (ADR-003).

1. Data: remove the retired ``workspace_id='platform'`` ``skills`` rows. These were
   materialized by an older operator that forked every built-in skill into a single
   shared "platform" workspace. The current operator no longer materializes tenant
   ``skills`` rows on sync (built-ins live only as ``registry_items``, forked
   copy-on-write per workspace), so these rows are dead leftovers — unreferenced by
   any agent, invisible in every workspace listing, yet still occupying every
   catalog item's ``registry_item_id`` globally.

2. Schema: ``uq_skills_registry_item`` was a *global* partial unique index on
   ``registry_item_id`` alone, so a catalog item could be forked into ``skills``
   only once across the whole system. Forking is per-workspace copy-on-write, so the
   constraint must be composite ``(workspace_id, registry_item_id)`` — each workspace
   gets its own fork of the same built-in.

Together these were a hard block: the platform rows squatted every
``registry_item_id`` under the global index, so ``POST /v1/skills/{id}/install`` from
any real workspace hit a ``UniqueViolationError`` (surfacing to the UI as a 500 →
``Unexpected token 'I' ... is not valid JSON``).

The data deletion is irreversible: downgrade restores only the schema (global index),
not the dropped rows.

Revision ID: 20260628_0001_skill_reg_uq
Revises: 20260624_0002_post_merge
Create Date: 2026-06-28 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260628_0001_skill_reg_uq"
down_revision: str | None = "20260624_0002_post_merge"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Drop the retired platform-workspace skill rows (and their install records).
    #    agent_skills / skill_members rows are removed via ON DELETE CASCADE.
    op.execute(sa.text("DELETE FROM registry_item_installs WHERE workspace_id = 'platform'"))
    op.execute(sa.text("DELETE FROM skills WHERE workspace_id = 'platform'"))

    # 2. Re-scope provenance uniqueness from global to per-workspace.
    op.drop_index("uq_skills_registry_item", table_name="skills")
    op.create_index(
        "uq_skills_registry_item",
        "skills",
        ["workspace_id", "registry_item_id"],
        unique=True,
        postgresql_where=sa.text("registry_item_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Restore the global (registry_item_id only) partial unique index. The deleted
    # platform rows are not restored. This downgrade fails if any catalog item has
    # been forked by more than one workspace (which the global index forbids).
    op.drop_index("uq_skills_registry_item", table_name="skills")
    op.create_index(
        "uq_skills_registry_item",
        "skills",
        ["registry_item_id"],
        unique=True,
        postgresql_where=sa.text("registry_item_id IS NOT NULL"),
    )
