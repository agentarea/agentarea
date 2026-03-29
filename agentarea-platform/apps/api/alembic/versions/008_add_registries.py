"""Add registries and registry_items tables for app-store catalog

Supports multiple entity types (mcp_servers, skills) via registry_type.
Sync auto-creates specs; version updates require manual approval.

Revision ID: 008_add_registries
Revises: 007_add_api_keys
Create Date: 2026-03-13 00:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "008_add_registries"
down_revision: str = "007_add_api_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- registries: configured external sources --
    op.create_table(
        "registries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # registry_type: what kind of entities this registry contains
        sa.Column("registry_type", sa.String(50), nullable=False),  # "mcp_servers", "skills"
        # source_type: how to fetch — "url" (JSON/YAML bundle), "github", "api"
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("sync_mode", sa.String(50), nullable=False, server_default="manual"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_registries_workspace_id", "registries", ["workspace_id"])
    op.create_index("ix_registries_registry_type", "registries", ["registry_type"])

    # -- registry_items: cached catalog entries synced from registries --
    op.create_table(
        "registry_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column(
            "registry_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("registries.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Unique identifier within this registry (includes variant if needed)
        sa.Column("external_id", sa.String(500), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(100), nullable=True),
        # Full spec from the registry source — entity-specific details live here
        sa.Column("spec", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default="[]"),
        # Generic entity linkage — points to mcp_servers.id or skills.id
        sa.Column("installed_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("update_available", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("installed_version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_registry_items_workspace_id", "registry_items", ["workspace_id"])
    op.create_index("ix_registry_items_registry_id", "registry_items", ["registry_id"])
    op.create_index("ix_registry_items_external_id", "registry_items", ["external_id"])
    # external_id is unique within a registry
    op.create_unique_constraint(
        "uq_registry_items_registry_external",
        "registry_items",
        ["registry_id", "external_id"],
    )

    # -- Provenance FK on mcp_servers --
    op.add_column(
        "mcp_servers",
        sa.Column("registry_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_mcp_servers_registry_item_id", "mcp_servers", ["registry_item_id"])

    # -- Provenance FK on skills --
    op.add_column(
        "skills",
        sa.Column("registry_item_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_skills_registry_item_id", "skills", ["registry_item_id"])


def downgrade() -> None:
    op.drop_index("ix_skills_registry_item_id", table_name="skills")
    op.drop_column("skills", "registry_item_id")
    op.drop_index("ix_mcp_servers_registry_item_id", table_name="mcp_servers")
    op.drop_column("mcp_servers", "registry_item_id")
    op.drop_table("registry_items")
    op.drop_table("registries")
