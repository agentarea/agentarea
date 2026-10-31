"""egress_exits: the proxies an MCP instance may leave through (ADR-0039)

An exit is a workspace's own proxy, its password held by reference to the secret
catalog, or one the platform supplies to every workspace (managed_by =
'platform', written by the operator). An instance binds one by id in
json_spec.egress_exit.

Revision ID: 20261031_2000_egress_exits
Revises: 20261030_1200_reasoning_data
Create Date: 2026-10-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261031_2000_egress_exits"
down_revision: str | None = "20261030_1200_reasoning_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "egress_exits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("upstream_url", sa.String(512), nullable=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column(
            "password_secret_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("encrypted_secrets.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("via", sa.String(63), nullable=True),
        sa.Column("remote_dns", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "allow_plaintext_credentials", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("managed_by", sa.String(32), nullable=True),
        sa.UniqueConstraint("workspace_id", "name", name="uq_egress_exits_workspace_name"),
        sa.CheckConstraint(
            "upstream_url IS NOT NULL OR (COALESCE(managed_by, '') = 'platform' AND via IS NOT NULL)",
            name="ck_egress_exits_route",
        ),
    )


def downgrade() -> None:
    op.drop_table("egress_exits")
