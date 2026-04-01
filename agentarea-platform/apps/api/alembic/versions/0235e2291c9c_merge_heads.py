"""merge heads

Revision ID: 0235e2291c9c
Revises: aa1b2c3d4e5f, gg1_add_icon_to_mcp_servers
Create Date: 2026-03-27 10:17:29.725661

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '0235e2291c9c'
down_revision: str | None = ('aa1b2c3d4e5f', 'gg1_add_icon_to_mcp_servers')
branch_labels: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
