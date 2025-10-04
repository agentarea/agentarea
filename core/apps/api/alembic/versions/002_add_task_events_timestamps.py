"""add_task_events_timestamps

Revision ID: 002_add_task_events_timestamps
Revises: 0d9d18a225c6
Create Date: 2025-01-18 14:30:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "002_add_task_events_timestamps"
down_revision: str | None = "0d9d18a225c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op: task_events uses 'timestamp' for event time; no created_at/updated_at needed."""
    pass


def downgrade() -> None:
    """No-op."""
    pass
