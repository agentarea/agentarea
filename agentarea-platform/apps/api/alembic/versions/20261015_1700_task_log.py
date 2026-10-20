"""task_conversation_entries becomes the task's log: kinds, ids, chain and meta

A row is a ``message`` (a turn), a ``compaction`` (the summary of everything
before it, formerly ``summary``) or an ``event`` (something that happened at a
moment, never sent to the model). Each row gets the workflow's ``event_id``
(unique per task: a retried append writes nothing twice), the ``execution_id``
and ``iteration`` it belongs to, the task's ``correlation_id`` and
``causation_id``, its ``meta`` (attributes such as the answering model or a
tool's exit code) and ``body_ref``, the stored body of a row too large to keep
inline.

No customers: existing rows get fresh event ids, nothing else is backfilled.

Revision ID: 20261015_1700_task_log
Revises: 20261015_1600_bus_on_broker
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_1700_task_log"
down_revision: str | None = "20261015_1600_bus_on_broker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "task_conversation_entries"


def upgrade() -> None:
    op.execute("UPDATE task_conversation_entries SET kind = 'compaction' WHERE kind = 'summary'")
    op.add_column(
        _TABLE,
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.alter_column(_TABLE, "event_id", server_default=None)
    op.add_column(_TABLE, sa.Column("execution_id", sa.String(255), nullable=True))
    op.add_column(_TABLE, sa.Column("iteration", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("meta", postgresql.JSONB(), nullable=True))
    op.add_column(_TABLE, sa.Column("correlation_id", sa.String(255), nullable=True))
    op.add_column(_TABLE, sa.Column("causation_id", sa.String(255), nullable=True))
    op.add_column(_TABLE, sa.Column("body_ref", sa.String(512), nullable=True))
    op.create_unique_constraint(
        "uq_task_conversation_entries_event", _TABLE, ["task_id", "event_id"]
    )
    op.create_check_constraint(
        "ck_task_conversation_entries_kind", _TABLE, "kind IN ('message', 'compaction', 'event')"
    )
    op.create_index("ix_task_conversation_entries_correlation_id", _TABLE, ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_task_conversation_entries_correlation_id", table_name=_TABLE)
    op.drop_constraint("ck_task_conversation_entries_kind", _TABLE, type_="check")
    op.drop_constraint("uq_task_conversation_entries_event", _TABLE, type_="unique")
    for column in (
        "body_ref",
        "causation_id",
        "correlation_id",
        "meta",
        "iteration",
        "execution_id",
        "event_id",
    ):
        op.drop_column(_TABLE, column)
    op.execute("DELETE FROM task_conversation_entries WHERE kind = 'event'")
    op.execute("UPDATE task_conversation_entries SET kind = 'summary' WHERE kind = 'compaction'")
