"""Trigger batch windows: a stream trigger's batch setting, and its held reactions found fast

``triggers.batch`` is ``{"window": "1h", "max_events": 50}`` for a stream
trigger that fires once per batch of events; null fires per event. A reaction
held in an open batch is a ``trigger_executions`` row with verdict ``batched``;
switching a trigger off or deleting it looks those up by trigger.

Revision ID: 20261019_2100_trigger_batch
Revises: 20261019_2000_stream_processors
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_2100_trigger_batch"
down_revision: str | None = "20261019_2000_stream_processors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("triggers", sa.Column("batch", sa.JSON(), nullable=True))
    op.create_index(
        "ix_trigger_executions_batched",
        "trigger_executions",
        ["trigger_id"],
        postgresql_where=sa.text("verdict = 'batched'"),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE trigger_executions SET verdict = 'skipped', status = 'skipped', "
        "reason = 'batch windows were removed' WHERE verdict = 'batched'"
    )
    op.drop_index("ix_trigger_executions_batched", table_name="trigger_executions")
    op.drop_column("triggers", "batch")
