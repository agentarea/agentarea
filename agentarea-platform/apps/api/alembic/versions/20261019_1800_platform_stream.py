"""The platform stream: a task's causation depth, one platform stream per workspace

``tasks.depth`` is the causation depth of the event that started the task (0
when no event did); the task's outcome lands in the platform stream one level
deeper, so a trigger chain through it is bounded like a forward chain.

A workspace has at most one platform stream, and the name ``platform`` is
its: a custom stream already holding it is renamed.

Revision ID: 20261019_1800_platform_stream
Revises: 20261019_1600_mcp_events_out
Create Date: 2026-10-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_1800_platform_stream"
down_revision: str | None = "20261019_1600_mcp_events_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("depth", sa.Integer(), nullable=False, server_default="0"))
    op.execute(
        "UPDATE streams SET name = 'platform (custom)' "
        "WHERE name = 'platform' AND kind <> 'platform'"
    )
    op.create_index(
        "uq_streams_platform",
        "streams",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'platform'"),
    )
    op.create_check_constraint(
        "ck_stream_sources_platform",
        "stream_sources",
        "kind <> 'platform' OR webhook_id IS NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_stream_sources_platform", "stream_sources", type_="check")
    op.drop_index("uq_streams_platform", table_name="streams")
    op.drop_column("tasks", "depth")
