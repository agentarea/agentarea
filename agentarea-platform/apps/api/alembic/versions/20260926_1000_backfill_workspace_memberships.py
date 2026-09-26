"""Every member who joined by invitation has a membership row

Members admitted before membership rows were written have the graph tuple and no
row. Code now reads the row as the record of who is still in: removal leaves a
user's graph grants alone while their row exists, and the reconcile script's
``--revoke-ended-memberships`` deletes the grants of anyone without one. So every
accepted invitation gets the row it should have produced, dated when it was
accepted.

Owners get none: every reader adds ``workspaces.owner_user_id`` beside the rows,
and neither ``create_shared`` nor ``ensure_personal`` writes one for them.

Members admitted some other way are only in the graph, which a migration cannot
read; the reconcile script's ``--backfill-memberships-from-graph`` covers them.

Revision ID: 20260926_1000_membership_rows
Revises: 20260925_1700_outbox_retry_at
Create Date: 2026-09-26 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_1000_membership_rows"
down_revision: str | None = "20260925_1700_outbox_retry_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BACKFILL_ACCEPTED_INVITATIONS = sa.text(
    """
    INSERT INTO workspace_memberships
        (id, workspace_id, user_id, invitation_id, created_at, updated_at)
    SELECT gen_random_uuid(), workspace_id, user_id, invitation_id, joined_at, joined_at
    FROM (
        SELECT DISTINCT ON (invitation.workspace_id, invitation.accepted_by_user_id)
            invitation.workspace_id,
            invitation.accepted_by_user_id AS user_id,
            invitation.id AS invitation_id,
            COALESCE(invitation.accepted_at, workspace.created_at, invitation.created_at)
                AS joined_at
        FROM workspace_invitations AS invitation
        LEFT JOIN workspaces AS workspace ON workspace.id = invitation.workspace_id
        WHERE invitation.status = 'accepted'
          AND invitation.accepted_by_user_id IS NOT NULL
        ORDER BY
            invitation.workspace_id,
            invitation.accepted_by_user_id,
            invitation.accepted_at NULLS LAST,
            invitation.created_at
    ) AS accepted
    ON CONFLICT (workspace_id, user_id) DO NOTHING
    """
)


def upgrade() -> None:
    op.execute(BACKFILL_ACCEPTED_INVITATIONS)


def downgrade() -> None:
    # The backfilled rows are indistinguishable from rows admission wrote.
    pass
