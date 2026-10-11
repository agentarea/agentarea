"""tool_call_approvals: a person's yes to one exact tool call a client could not wait on

A client call the workspace policy holds for approval is recorded here and
answered with an approval link; the client's retry with the same arguments
(matched by arguments_hash) runs it once the call is approved.

Revision ID: 20261006_1200_tool_call_approval
Revises: 20261006_0920_webhook_backfill
Create Date: 2026-10-06 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261006_1200_tool_call_approval"
down_revision: str | None = "20261008_1400_openapi_qparams"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_call_approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("client_name", sa.String(255), nullable=True),
        sa.Column("mcp_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("connector", sa.String(255), nullable=False),
        sa.Column("tool", sa.String(255), nullable=False),
        sa.Column("policy_name", sa.String(512), nullable=False),
        sa.Column("arguments", postgresql.JSONB(), nullable=False),
        sa.Column("arguments_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("approvers", postgresql.JSONB(), nullable=False),
        sa.Column("decided_by", sa.String(255), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tool_call_approvals_workspace_id", "tool_call_approvals", ["workspace_id"])
    op.create_index("ix_tool_call_approvals_created_by", "tool_call_approvals", ["created_by"])
    op.create_index(
        "ix_tool_call_approvals_call",
        "tool_call_approvals",
        ["workspace_id", "created_by", "tool", "arguments_hash"],
    )
    op.create_index(
        "ix_tool_call_approvals_workspace_status",
        "tool_call_approvals",
        ["workspace_id", "status"],
    )
    op.create_index(
        "uq_tool_call_approvals_pending",
        "tool_call_approvals",
        ["workspace_id", "created_by", "mcp_instance_id", "tool", "arguments_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_table("tool_call_approvals")
