"""Record who asked for a trigger run, when a person did.

A trigger execution had no way to say what caused it. Until now there was only
ever one cause per trigger -- the schedule came due, or the webhook was called
-- so the row did not need to answer it. The "run now" button adds a second
cause, and the two have to be told apart: a manual test run should not read as
the schedule having fired.

``created_by`` cannot carry this. It is filled on every execution, including
the ones the scheduler writes, so it records whose context wrote the row rather
than who asked for the run.

NULL means the trigger fired itself. Existing rows are therefore correct as
they stand, which is why the column is nullable rather than backfilled.

Revision ID: 20260917_1100_exec_fired_by
Revises: 20260915_1400_audit_append_only
Create Date: 2026-09-17 11:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260917_1100_exec_fired_by"
down_revision: str | None = "20260915_1400_audit_append_only"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trigger_executions",
        sa.Column("fired_by", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_trigger_executions_fired_by",
        "trigger_executions",
        ["fired_by"],
    )


def downgrade() -> None:
    op.drop_index("ix_trigger_executions_fired_by", table_name="trigger_executions")
    op.drop_column("trigger_executions", "fired_by")
