"""merge 4 divergent alembic heads into a single head

Four feature branches each left their own head, so `alembic upgrade head`
became ambiguous ("Multiple head revisions are present") and the db-migration
Job stopped applying migrations — production froze on an old revision. This
no-op merge reunites them so there is exactly one head again.

Merged heads:
- 010_add_a2ui_enabled
- 20260618_1200_reg_item_installs
- gg2_add_wallet_fk_cascades
- jj1_docker_url_nullable

Revision ID: 20260624_0001_merge_heads
Create Date: 2026-06-24 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260624_0001_merge_heads"
down_revision: str | None = ("010_add_a2ui_enabled", "20260618_1200_reg_item_installs", "gg2_add_wallet_fk_cascades", "jj1_docker_url_nullable")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: merge point only."""
    pass


def downgrade() -> None:
    """No-op: merge point only."""
    pass
