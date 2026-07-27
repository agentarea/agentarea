"""Track when an MCP server instance was last used

Lazy provisioning starts an instance's container on demand, but nothing ever
stopped it: no column recorded activity, and the container monitor only sweeps
verification state, so an instance started once ran until something else killed
it. This adds the timestamp the MCP proxy stamps on each call, which is what
lets the control plane tell an idle instance from a busy one and stop it.

Nullable with no backfill on purpose. NULL means "never observed through the
proxy", and the reaper treats that as not-idle rather than idle — an instance
predating this column must not be stopped just because nothing recorded a use
yet. The first proxied call sets it and the instance joins the normal cycle.

Revision ID: 20260727_0100_mcp_last_used
Revises: 20260719_0100_approval_rules
Create Date: 2026-07-27 01:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0100_mcp_last_used"
down_revision: str | None = "20260719_0100_approval_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "mcp_server_instances",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    # The reaper scans for idle instances across the whole table on a timer, so
    # it filters on this column rather than looking rows up by id.
    op.create_index(
        "ix_mcp_server_instances_last_used_at",
        "mcp_server_instances",
        ["last_used_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_mcp_server_instances_last_used_at", table_name="mcp_server_instances")
    op.drop_column("mcp_server_instances", "last_used_at")
