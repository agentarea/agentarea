"""Drop the task_summary view: the summary reads tasks and cost_entries (wiki ADR-0042)

The view rolled a task up from the old ``task_events``. The summary endpoint now
reads the run's times, answer and error from ``tasks`` and its spend from
``cost_entries``. No customers: downgrade does not rebuild the view.

Revision ID: 20261015_1500_drop_task_summary
Revises: 20261014_2000_media_prices
Create Date: 2026-10-15 15:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261015_1500_drop_task_summary"
down_revision: str | None = "20261014_2000_media_prices"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW IF EXISTS task_summary")


def downgrade() -> None:
    pass
