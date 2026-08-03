"""Move MCP liveness into control-plane-owned runtime tables

The old column required every caller to report use. The Go demand gateway now
observes every container-backed request and records renewable request leases.
Runtime state is independent from desired instance state and verification, so
reaping a workload never invalidates discovered tools or asks Python to
provision it again.

Revision ID: 20260730_0100_drop_last_used
Revises: 20260727_0100_mcp_last_used
Create Date: 2026-07-30 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260730_0100_drop_last_used"
down_revision: str | None = "20260727_0100_mcp_last_used"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_runtime_instances",
        sa.Column(
            "instance_id",
            sa.UUID(),
            sa.ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "state IN ('dormant','starting','ready','reaping','failed')",
            name="ck_mcp_runtime_instances_state",
        ),
    )
    op.create_index(
        "ix_mcp_runtime_instances_idle",
        "mcp_runtime_instances",
        ["state", "last_used_at"],
    )
    op.create_table(
        "mcp_runtime_request_leases",
        sa.Column("request_id", sa.UUID(), primary_key=True),
        sa.Column(
            "instance_id",
            sa.UUID(),
            sa.ForeignKey("mcp_runtime_instances.instance_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_mcp_runtime_request_leases_instance_expiry",
        "mcp_runtime_request_leases",
        ["instance_id", "expires_at"],
    )
    op.drop_index("ix_mcp_server_instances_last_used_at", table_name="mcp_server_instances")
    op.drop_column("mcp_server_instances", "last_used_at")


def downgrade() -> None:
    op.add_column(
        "mcp_server_instances",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_mcp_server_instances_last_used_at",
        "mcp_server_instances",
        ["last_used_at"],
    )
    op.drop_index(
        "ix_mcp_runtime_request_leases_instance_expiry",
        table_name="mcp_runtime_request_leases",
    )
    op.drop_table("mcp_runtime_request_leases")
    op.drop_index("ix_mcp_runtime_instances_idle", table_name="mcp_runtime_instances")
    op.drop_table("mcp_runtime_instances")
