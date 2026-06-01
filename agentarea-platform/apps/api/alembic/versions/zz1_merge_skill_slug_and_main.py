"""merge skill-slug branch with main

Ties together the two migration heads that result from merging ``main`` into
the workspace-scoped-slug line:
  - ``rr1_drop_workspace_settings`` (main),
  - ``qq1_add_skill_slug`` (skill slug + catalog provenance dedup).

No schema changes — this is a pure alembic merge revision.

Revision ID: zz1_merge_skill_slug_and_main
Revises: rr1_drop_workspace_settings, qq1_add_skill_slug
Create Date: 2026-06-01
"""

from collections.abc import Sequence

revision: str = "zz1_merge_skill_slug_and_main"
down_revision: tuple[str, ...] = ("rr1_drop_workspace_settings", "qq1_add_skill_slug")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
