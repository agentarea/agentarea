"""merge platform providers and audit append-only

Two branches reached main independently: the operator's platform-provider
migration and this branch's audit append-only trigger, which sits on top of the
tasks.user_id drop. Neither touches the other's tables, so the merge is a
pure join with nothing to do in either direction.

Revision ID: 70db8106b8f2
Revises: 20260915_1000_platform_providers, 20260915_1400_audit_append_only
Create Date: 2026-09-17 12:17:22.860769
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "70db8106b8f2"
down_revision: str | None = (
    "20260915_1000_platform_providers",
    "20260915_1400_audit_append_only",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
