"""Add workspace-scoped registry item install state.

Revision ID: 20260618_1200_reg_item_installs
Revises: 20260616_1200_drop_tps
Create Date: 2026-06-18 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260618_1200_reg_item_installs"
down_revision: str = "20260616_1200_drop_tps"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registry_item_installs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("registry_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("installed_entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installed_version", sa.String(100), nullable=True),
        sa.ForeignKeyConstraint(
            ["registry_item_id"],
            ["registry_items.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "registry_item_id",
            "workspace_id",
            name="uq_registry_item_installs_item_workspace",
        ),
    )
    op.create_index(
        "ix_registry_item_installs_registry_item_id",
        "registry_item_installs",
        ["registry_item_id"],
    )
    op.create_index(
        "ix_registry_item_installs_workspace_id",
        "registry_item_installs",
        ["workspace_id"],
    )

    op.execute(
        """
        INSERT INTO registry_item_installs (
            id,
            created_at,
            updated_at,
            registry_item_id,
            workspace_id,
            installed_entity_id,
            installed_version
        )
        SELECT DISTINCT ON (a.registry_item_id::uuid, a.workspace_id)
            gen_random_uuid(),
            now(),
            now(),
            a.registry_item_id::uuid,
            a.workspace_id,
            a.id,
            COALESCE(ri.installed_version, ri.version)
        FROM agents a
        JOIN registry_items ri ON ri.id = a.registry_item_id::uuid
        WHERE a.registry_item_id IS NOT NULL
          AND a.registry_item_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        ORDER BY a.registry_item_id::uuid, a.workspace_id, a.updated_at DESC
        ON CONFLICT (registry_item_id, workspace_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO registry_item_installs (
            id,
            created_at,
            updated_at,
            registry_item_id,
            workspace_id,
            installed_entity_id,
            installed_version
        )
        SELECT DISTINCT ON (s.registry_item_id, s.workspace_id)
            gen_random_uuid(),
            now(),
            now(),
            s.registry_item_id,
            s.workspace_id,
            s.id,
            COALESCE(ri.installed_version, ri.version)
        FROM skills s
        JOIN registry_items ri ON ri.id = s.registry_item_id
        WHERE s.registry_item_id IS NOT NULL
        ORDER BY s.registry_item_id, s.workspace_id, s.updated_at DESC
        ON CONFLICT (registry_item_id, workspace_id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index("ix_registry_item_installs_workspace_id", table_name="registry_item_installs")
    op.drop_index(
        "ix_registry_item_installs_registry_item_id",
        table_name="registry_item_installs",
    )
    op.drop_table("registry_item_installs")
