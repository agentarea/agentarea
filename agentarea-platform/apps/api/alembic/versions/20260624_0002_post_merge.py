"""linear no-op after the 4-head merge (keeps a non-merge tip)

The merge migration ``20260624_0001_merge_heads`` reunites four divergent heads,
but a merge node cannot be the tip: ``alembic downgrade -1`` from a merge raises
"Ambiguous walk" (it cannot pick which branch to walk down), which breaks the
CI migrations-gate downgrade/upgrade roundtrip. This trivial linear revision
sits on top of the merge so the single head is an ordinary (non-merge) node and
the roundtrip is unambiguous. No schema change.

Revision ID: 20260624_0002_post_merge
Revises: 20260624_0001_merge_heads
Create Date: 2026-06-24 00:01:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260624_0002_post_merge"
down_revision: str | None = "20260624_0001_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: linear tip above the merge."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
