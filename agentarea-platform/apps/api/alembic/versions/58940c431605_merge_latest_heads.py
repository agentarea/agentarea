"""merge latest heads

Revision ID: 58940c431605
Revises: 010_add_a2ui_enabled, gg2_add_wallet_fk_cascades, jj1_docker_url_nullable
Create Date: 2026-04-01 11:12:27.259186

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "58940c431605"
down_revision: str | None = (
    "010_add_a2ui_enabled",
    "gg2_add_wallet_fk_cascades",
    "jj1_docker_url_nullable",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
