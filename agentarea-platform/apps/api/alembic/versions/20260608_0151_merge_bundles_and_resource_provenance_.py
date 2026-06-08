"""merge bundles and resource provenance heads

Revision ID: 20260607_0001_merge_heads
Revises: 20260603_installed_bundles, 20260606_0900_agent_reg_prov
Create Date: 2026-06-08 01:51:56.045470

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260607_0001_merge_heads"
down_revision: str | None = ("20260603_installed_bundles", "20260606_0900_agent_reg_prov")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
