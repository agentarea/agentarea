"""Merge the two live heads so `alembic upgrade head` resolves again.

Revision ID: 20260915_0900_merge_heads
Revises: 20260908_1000_multi_catalog_conn, 20260907_1200_drop_defaults
Create Date: 2026-09-15 09:00:00.000000

Two branches landed on main independently and each kept its own head:

    20260908_1000_multi_catalog_conn   (catalog connections)
    20260907_1200_drop_defaults        (principal column defaults)

With more than one head, ``alembic upgrade head`` refuses to pick — so CI's
migration step and any fresh install have been failing on main since the second
one merged, and every migration written afterwards is unreachable.

Empty on purpose. A merge revision states that two lines of schema history are
compatible and nothing more; putting a schema change in one hides that change
behind a name nobody reads as a change. Same shape as 58940c431605.
"""

from collections.abc import Sequence

revision: str = "20260915_0900_merge_heads"
down_revision: str | Sequence[str] | None = (
    "20260908_1000_multi_catalog_conn",
    "20260907_1200_drop_defaults",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
