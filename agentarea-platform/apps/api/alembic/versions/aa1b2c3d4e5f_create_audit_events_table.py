"""Create audit_events table.

Revision ID: aa1b2c3d4e5f
Revises: ff9ec6b67386
Create Date: 2026-03-27

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

# revision identifiers, used by Alembic.
revision = "aa1b2c3d4e5f"
down_revision = "ff9ec6b67386"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        # Who
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("actor_type", sa.String(50), nullable=False, server_default="user"),
        # Where
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("source_ip", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("request_id", sa.String(255), nullable=True),
        # What
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        # Changes
        sa.Column("changes", JSONB, nullable=True),
        # Context
        sa.Column("event_metadata", JSONB, nullable=False, server_default="{}"),
    )

    op.create_index(
        "ix_audit_events_workspace_created",
        "audit_events",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_actor",
        "audit_events",
        ["workspace_id", "actor_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_resource",
        "audit_events",
        ["workspace_id", "resource_type", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_audit_events_action",
        "audit_events",
        ["workspace_id", "action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_events_action")
    op.drop_index("ix_audit_events_resource")
    op.drop_index("ix_audit_events_actor")
    op.drop_index("ix_audit_events_workspace_created")
    op.drop_table("audit_events")
