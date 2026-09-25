"""Stored trigger task parameters no longer carry channel_origin

Triggers created before channel_origin was refused on create kept it in
task_parameters. It is never copied onto a run, and the edit form echoed it
back on every save. Remove it from the stored rows; there is nothing to
restore on downgrade.

Revision ID: 20260925_1500_trg_channel_origin
Revises: 20260925_1400_inv_granted_at
Create Date: 2026-09-25 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_1500_trg_channel_origin"
down_revision: str | None = "20260925_1400_inv_granted_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE triggers "
        "SET task_parameters = (task_parameters::jsonb - 'channel_origin')::json "
        "WHERE task_parameters::jsonb -> 'channel_origin' IS NOT NULL"
    )


def downgrade() -> None:
    pass
