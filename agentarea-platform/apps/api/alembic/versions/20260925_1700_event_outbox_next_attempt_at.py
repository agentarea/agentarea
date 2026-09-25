"""An outbox row can wait before its next attempt

Rows the relay performs itself (taking a removed member's access out of the
graph) are retried until they succeed instead of giving up after a fixed number
of attempts, with exponential backoff between attempts. ``next_attempt_at`` is
when the row is due again; NULL means now, which is every row published to the
broker.

Revision ID: 20260925_1700_outbox_retry_at
Revises: 20260925_1600_money_numeric
Create Date: 2026-09-25 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260925_1700_outbox_retry_at"
down_revision: str | None = "20260925_1600_money_numeric"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event_outbox", sa.Column("next_attempt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("event_outbox", "next_attempt_at")
