"""An invitation records when it granted membership

Accepting an invitation granted membership again whenever the acceptor held no
membership row. Removals made before invitations were revoked on removal left
the invitation ACCEPTED and deleted the row, so replaying the old link let the
removed member back in. An invitation now grants only until
``membership_granted_at`` is set, and every invitation already accepted is
treated as having granted.

Revision ID: 20260925_1400_inv_granted_at
Revises: 20260925_1300_policy_managed_by
Create Date: 2026-09-25 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_1400_inv_granted_at"
down_revision: str | None = "20260925_1300_policy_managed_by"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace_invitations",
        sa.Column("membership_granted_at", sa.DateTime(), nullable=True),
    )
    op.execute(
        "UPDATE workspace_invitations "
        "SET membership_granted_at = COALESCE(accepted_at, now()) "
        "WHERE status = 'accepted'"
    )


def downgrade() -> None:
    op.drop_column("workspace_invitations", "membership_granted_at")
