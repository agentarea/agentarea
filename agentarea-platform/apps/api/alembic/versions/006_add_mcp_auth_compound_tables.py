"""Add MCP auth configs, OAuth links/sessions, compound MCPs and compound skills

Revision ID: 006_add_mcp_auth_compound_tables
Revises: 005_add_skills_table
Create Date: 2026-03-01 00:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "006_add_mcp_auth_compound_tables"
down_revision: str = "005_add_skills_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ========================================
    # 1. MCP AUTH CONFIGS TABLE
    # ========================================
    op.create_table(
        "mcp_auth_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Auth type: api_key | bearer | oauth2
        sa.Column("auth_type", sa.String(50), nullable=False),
        # Non-sensitive config (header name, token_url, client_id, scopes, etc.)
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        # Encrypted credentials reference key stored in secret manager
        sa.Column("secret_key", sa.String(512), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_mcp_auth_configs_workspace_id", "mcp_auth_configs", ["workspace_id"])
    op.create_index("ix_mcp_auth_configs_auth_type", "mcp_auth_configs", ["auth_type"])

    # ========================================
    # 2. ADD auth_config_id FK TO mcp_server_instances
    # ========================================
    op.add_column(
        "mcp_server_instances",
        sa.Column(
            "auth_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_mcp_server_instances_auth_config_id",
        "mcp_server_instances",
        ["auth_config_id"],
    )

    # ========================================
    # 3. COMPOUND MCPS TABLE
    # ========================================
    op.create_table(
        "compound_mcps",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        # Routing mode: parallel | fallback | conditional
        sa.Column("routing_mode", sa.String(50), nullable=False, server_default="parallel"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_compound_mcps_workspace_id", "compound_mcps", ["workspace_id"])

    # ========================================
    # 4. COMPOUND MCP MEMBERS JUNCTION TABLE
    # ========================================
    op.create_table(
        "compound_mcp_members",
        sa.Column(
            "compound_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compound_mcps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "mcp_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        # Per-member config: namespace prefix, aliases, condition expression
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_primary_key(
        "pk_compound_mcp_members", "compound_mcp_members", ["compound_id", "mcp_instance_id"]
    )
    op.create_index("ix_compound_mcp_members_compound_id", "compound_mcp_members", ["compound_id"])
    op.create_index(
        "ix_compound_mcp_members_instance_id", "compound_mcp_members", ["mcp_instance_id"]
    )

    # ========================================
    # 5. COMPOUND SKILLS TABLE
    # ========================================
    op.create_table(
        "compound_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.String(50), nullable=False, server_default="1.0.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_compound_skills_workspace_id", "compound_skills", ["workspace_id"])

    # ========================================
    # 6. COMPOUND SKILL MEMBERS JUNCTION TABLE
    # ========================================
    op.create_table(
        "compound_skill_members",
        sa.Column(
            "compound_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("compound_skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default="true"),
        # dependency_skill_ids: list of skill IDs within the compound that must run first
        sa.Column(
            "dependencies",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_primary_key(
        "pk_compound_skill_members", "compound_skill_members", ["compound_id", "skill_id"]
    )
    op.create_index(
        "ix_compound_skill_members_compound_id", "compound_skill_members", ["compound_id"]
    )
    op.create_index("ix_compound_skill_members_skill_id", "compound_skill_members", ["skill_id"])

    # ========================================
    # 7. MCP OAUTH LINKS TABLE
    # ========================================
    op.create_table(
        "mcp_oauth_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column(
            "mcp_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_server_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Unique token embedded in the shareable URL
        sa.Column("token", sa.String(128), nullable=False, unique=True),
        # Access control: workspace | public
        sa.Column("access_control", sa.String(50), nullable=False, server_default="workspace"),
        # OAuth provider config (provider, client_id, etc.) - non-sensitive
        sa.Column(
            "provider_config",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )
    op.create_index("ix_mcp_oauth_links_workspace_id", "mcp_oauth_links", ["workspace_id"])
    op.create_index("ix_mcp_oauth_links_token", "mcp_oauth_links", ["token"])
    op.create_index("ix_mcp_oauth_links_instance_id", "mcp_oauth_links", ["mcp_instance_id"])

    # ========================================
    # 8. MCP OAUTH SESSIONS TABLE
    # ========================================
    op.create_table(
        "mcp_oauth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "link_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_oauth_links.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Opaque session token issued as cookie value
        sa.Column("session_token", sa.String(256), nullable=False, unique=True),
        # Identity info returned from OAuth provider
        sa.Column(
            "identity",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_mcp_oauth_sessions_link_id", "mcp_oauth_sessions", ["link_id"])
    op.create_index("ix_mcp_oauth_sessions_token", "mcp_oauth_sessions", ["session_token"])


def downgrade() -> None:
    op.drop_table("mcp_oauth_sessions")

    op.drop_index("ix_mcp_oauth_links_instance_id", table_name="mcp_oauth_links")
    op.drop_index("ix_mcp_oauth_links_token", table_name="mcp_oauth_links")
    op.drop_index("ix_mcp_oauth_links_workspace_id", table_name="mcp_oauth_links")
    op.drop_table("mcp_oauth_links")

    op.drop_index("ix_compound_skill_members_skill_id", table_name="compound_skill_members")
    op.drop_index("ix_compound_skill_members_compound_id", table_name="compound_skill_members")
    op.drop_table("compound_skill_members")

    op.drop_index("ix_compound_skills_workspace_id", table_name="compound_skills")
    op.drop_table("compound_skills")

    op.drop_index("ix_compound_mcp_members_instance_id", table_name="compound_mcp_members")
    op.drop_index("ix_compound_mcp_members_compound_id", table_name="compound_mcp_members")
    op.drop_table("compound_mcp_members")

    op.drop_index("ix_compound_mcps_workspace_id", table_name="compound_mcps")
    op.drop_table("compound_mcps")

    op.drop_index("ix_mcp_server_instances_auth_config_id", table_name="mcp_server_instances")
    op.drop_column("mcp_server_instances", "auth_config_id")

    op.drop_index("ix_mcp_auth_configs_auth_type", table_name="mcp_auth_configs")
    op.drop_index("ix_mcp_auth_configs_workspace_id", table_name="mcp_auth_configs")
    op.drop_table("mcp_auth_configs")
