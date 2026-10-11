"""Add user_external_identities: messenger accounts recognised as platform users

A row says Telegram account ``external_id`` is user ``user_id``, proven by the
person from inside the messenger. At most one live link per account, enforced
by a partial unique index; a revoked link keeps its row.

Revision ID: 20261010_1000_user_ext_ids
Revises: 20261009_1210_openapi_qp_tools
Create Date: 2026-10-10 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_1000_user_ext_ids"
down_revision: str | None = "20261009_1210_openapi_qp_tools"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_external_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_external_identities_user_id", "user_external_identities", ["user_id"])
    op.create_index(
        "uq_user_external_identities_live",
        "user_external_identities",
        ["provider", "external_id"],
        unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_external_identities_live", table_name="user_external_identities")
    op.drop_index("ix_user_external_identities_user_id", table_name="user_external_identities")
    op.drop_table("user_external_identities")
