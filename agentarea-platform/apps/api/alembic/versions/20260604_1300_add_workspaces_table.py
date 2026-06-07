"""Add workspaces table (reify workspace as a first-class entity)

Turns the previously-opaque ``workspace_id`` string into a real row.
Additive only:
- no foreign keys from scoped tables (those can follow later),
- no backfill — personal workspaces are provisioned on demand with
  ``id == user_id`` so existing data stays valid,
- no ``parent_org_id`` — the organization layer is deferred until
  billing/SSO concretely require it.

Revision ID: 20260604_1300_workspaces_table
Revises: 20260604_1200_skill_collections
Create Date: 2026-06-04 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260604_1300_workspaces_table"
down_revision: str = "20260604_1200_skill_collections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="personal"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("owner_user_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_table("workspaces")
