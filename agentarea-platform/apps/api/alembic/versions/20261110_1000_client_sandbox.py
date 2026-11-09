"""A harness client says whether its runner's CLI runs in a sandbox

``clients.sandbox`` is sent with every turn: on, commands the CLI runs see only
the task's folder and reach only the allowed hosts; off, they run unconfined on
the runner's machine. It replaces the runner's own ``--sandbox`` flag, so the
setting is the client's, set by whoever may edit it, and shown where it is set.

Revision ID: 20261110_1000_client_sandbox
Revises: 20261109_1900_harness_agent
Create Date: 2026-11-10 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261110_1000_client_sandbox"
down_revision: str | None = "20261109_1900_harness_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("sandbox", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("clients", "sandbox")
