"""Drop clients.source_project_id — a client's bundle is its own attachments

The column made a client's effective tool set the union of its own attachments
and those of a linked project, which the API exposed as "pull from project"
while nothing was ever pulled. Two places could add a tool to one endpoint, and
neither showed the other. The client now carries exactly what is attached to it.

Reversible: the downgrade recreates the nullable column and its FK. The links
themselves are not restorable — dropping the column is the point.

Revision ID: 20260902_1000_drop_client_src
Revises: 20260831_1200_task_sched_at
Create Date: 2026-09-02 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "20260902_1000_drop_client_src"
down_revision: str | None = "20260831_1200_task_sched_at"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("clients", "source_project_id")


def downgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("source_project_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "clients_source_project_id_fkey",
        "clients",
        "projects",
        ["source_project_id"],
        ["id"],
        ondelete="SET NULL",
    )
