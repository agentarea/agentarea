"""A user secret records when its creator's ownership reached the graph

Using a secret is ``can_use_secret`` on ``resource:<secret id>``, which needs the
ownership tuples a create now writes. Every user secret made before has none;
``graph_granted_at`` stays null for them, and the reconcile grants each one its
creator and stamps it. A create whose grant succeeded stamps it at once.

Revision ID: 20261109_2200_secret_graph_grant
Revises: 20261109_1900_harness_agent
Create Date: 2026-11-09 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261109_2200_secret_graph_grant"
down_revision: str | None = "20261109_1900_harness_agent"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "encrypted_secrets",
        sa.Column("graph_granted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_encrypted_secrets_graph_pending",
        "encrypted_secrets",
        ["id"],
        postgresql_where=sa.text("owner_type IS NULL AND graph_granted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_encrypted_secrets_graph_pending", table_name="encrypted_secrets")
    op.drop_column("encrypted_secrets", "graph_granted_at")
