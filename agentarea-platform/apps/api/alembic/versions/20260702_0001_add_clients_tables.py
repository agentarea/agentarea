"""add clients tables

Revision ID: 20260702_0001_add_clients_tables
Revises: 20260628_0001_skill_reg_uq
Create Date: 2026-07-02 00:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260702_0001_add_clients_tables"
down_revision: str | None = "20260628_0001_skill_reg_uq"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False, server_default="harness"),
        sa.Column(
            "source_project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_clients_workspace_id", "clients", ["workspace_id"])
    op.create_index("ix_clients_created_by", "clients", ["created_by"])

    op.create_table(
        "client_skills",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )

    op.create_table(
        "client_mcp_instances",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "mcp_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("namespace_prefix", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("client_mcp_instances")
    op.drop_table("client_skills")
    op.drop_index("ix_clients_created_by", table_name="clients")
    op.drop_index("ix_clients_workspace_id", table_name="clients")
    op.drop_table("clients")
