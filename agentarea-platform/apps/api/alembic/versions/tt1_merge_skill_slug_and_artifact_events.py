"""merge skill slug and artifact event migration heads

Revision ID: tt1_merge_heads
Revises: qq1_add_skill_slug, ss1_add_artifact_events
Create Date: 2026-06-02
"""

from collections.abc import Sequence

revision: str = "tt1_merge_heads"
down_revision: tuple[str, str] | None = ("qq1_add_skill_slug", "ss1_add_artifact_events")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
