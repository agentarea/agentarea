"""Initial schema with all tables and proper workspace support

Revision ID: 001_initial_schema
Revises:
Create Date: 2025-01-08 12:00:00.000000

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create all tables with proper workspace and audit support."""
    # ========================================
    # AGENTS TABLE
    # ========================================
    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("model_id", sa.String(), nullable=True),
        sa.Column("tools_config", sa.JSON(), nullable=True),
        sa.Column("events_config", sa.JSON(), nullable=True),
        sa.Column("planning", sa.Boolean(), nullable=True),
        sa.Column("instruction", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, default="active"),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # ========================================
    # TASKS TABLE
    # ========================================
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, default="pending"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("execution_id", sa.String(255), nullable=True),
        sa.Column("user_id", sa.String(255), nullable=True),  # Legacy field, kept for compatibility
        sa.Column("task_metadata", sa.JSON(), nullable=True),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # MCP SERVERS TABLE
    # ========================================
    op.create_table(
        "mcp_servers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("docker_image_url", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, default="inactive"),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=False),
        sa.Column("env_schema", postgresql.JSON(), nullable=False, server_default="[]"),
        sa.Column("cmd", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        sa.Column("updated_by", sa.String(255), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # MCP SERVER INSTANCES TABLE
    # ========================================
    op.create_table(
        "mcp_server_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "server_spec_id", sa.String(255), nullable=True
        ),  # Changed from UUID FK to String
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, default="starting"),
        sa.Column("json_spec", sa.JSON(), nullable=False, server_default="{}"),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # LLM PROVIDER SPECS TABLE
    # ========================================
    op.create_table(
        "provider_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column("provider_key", sa.String(), nullable=False, unique=True),  # openai, anthropic
        sa.Column("name", sa.String(), nullable=False),  # OpenAI, Anthropic
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("provider_type", sa.String(), nullable=False),  # for LiteLLM
        sa.Column("icon", sa.String(), nullable=True),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, default=True),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # LLM PROVIDER CONFIGS TABLE
    # ========================================
    op.create_table(
        "provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "provider_spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_specs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),  # "My OpenAI", "Work OpenAI"
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("api_key", sa.String(), nullable=True),
        sa.Column("endpoint_url", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=False),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # LLM MODEL SPECS TABLE
    # ========================================
    op.create_table(
        "model_specs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "provider_spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_specs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_name", sa.String(), nullable=False),  # gpt-4, claude-3-opus
        sa.Column("display_name", sa.String(), nullable=False),  # GPT-4, Claude 3 Opus
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=False, default=4096),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # LLM MODEL INSTANCES TABLE
    # ========================================
    op.create_table(
        "model_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "provider_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("provider_configs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "model_spec_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("model_specs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),  # User-friendly name
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=False),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # TRIGGERS TABLE
    # ========================================
    op.create_table(
        "triggers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        # Basic trigger fields
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, default=""),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("task_parameters", sa.JSON(), nullable=False, default={}),
        sa.Column("conditions", sa.JSON(), nullable=False, default={}),
        # Rate limiting and safety
        sa.Column("failure_threshold", sa.Integer(), nullable=False, default=5),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, default=0),
        sa.Column("last_execution_at", sa.DateTime(), nullable=True),
        # Cron-specific fields
        sa.Column("cron_expression", sa.String(255), nullable=True),
        sa.Column("timezone", sa.String(100), nullable=True, default="UTC"),
        sa.Column("next_run_time", sa.DateTime(), nullable=True),
        # Webhook-specific fields
        sa.Column("webhook_id", sa.String(255), nullable=True),
        sa.Column("allowed_methods", sa.JSON(), nullable=True),
        sa.Column("webhook_type", sa.String(50), nullable=True, default="generic"),
        sa.Column("validation_rules", sa.JSON(), nullable=False, default={}),
        sa.Column("webhook_config", sa.JSON(), nullable=True),  # Generic webhook config
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # TRIGGER EXECUTIONS TABLE
    # ========================================
    op.create_table(
        "trigger_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        # Basic execution fields
        sa.Column(
            "trigger_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("triggers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=False, default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trigger_data", sa.JSON(), nullable=False, default={}),
        # Temporal workflow tracking
        sa.Column("workflow_id", sa.String(255), nullable=True),
        sa.Column("run_id", sa.String(255), nullable=True),
        # Workspace and audit fields
        sa.Column("workspace_id", sa.String(255), nullable=False, server_default="default"),
        sa.Column("created_by", sa.String(255), nullable=False, server_default="system"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # ========================================
    # CONSTRAINTS AND INDEXES
    # ========================================

    # Unique constraints
    op.create_unique_constraint(
        "uq_model_specs_provider_model", "model_specs", ["provider_spec_id", "model_name"]
    )

    # Workspace indexes for all tables
    tables_with_workspace = [
        "agents",
        "tasks",
        "mcp_servers",
        "mcp_server_instances",
        "provider_specs",
        "provider_configs",
        "model_specs",
        "model_instances",
        "triggers",
        "trigger_executions",
    ]

    for table in tables_with_workspace:
        op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])

    # Created_by indexes for tables that have it
    tables_with_created_by = [
        "agents",
        "tasks",
        "mcp_servers",
        "mcp_server_instances",
        "provider_specs",
        "provider_configs",
        "model_specs",
        "model_instances",
        "triggers",
        "trigger_executions",
    ]

    for table in tables_with_created_by:
        op.create_index(f"ix_{table}_created_by", table, ["created_by"])
        op.create_index(f"ix_{table}_workspace_created_by", table, ["workspace_id", "created_by"])

    # Specific functional indexes
    op.create_index("ix_agents_status", "agents", ["status"])
    op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_index("ix_tasks_agent_id", "tasks", ["agent_id"])
    op.create_index("ix_tasks_workspace_created", "tasks", ["workspace_id", "created_at"])

    op.create_index("ix_mcp_servers_status", "mcp_servers", ["status"])
    op.create_index("ix_mcp_servers_updated_by", "mcp_servers", ["updated_by"])
    op.create_index("ix_mcp_server_instances_status", "mcp_server_instances", ["status"])

    op.create_index("ix_provider_configs_active", "provider_configs", ["is_active"])
    op.create_index("ix_model_instances_active", "model_instances", ["is_active"])

    op.create_index("ix_triggers_agent_id", "triggers", ["agent_id"])
    op.create_index("ix_triggers_type", "triggers", ["trigger_type"])
    op.create_index("ix_triggers_active", "triggers", ["is_active"])
    op.create_index("ix_triggers_webhook_id", "triggers", ["webhook_id"])
    op.create_index("ix_triggers_next_run", "triggers", ["next_run_time"])

    op.create_index("ix_trigger_executions_trigger_id", "trigger_executions", ["trigger_id"])
    op.create_index("ix_trigger_executions_status", "trigger_executions", ["status"])
    op.create_index("ix_trigger_executions_executed_at", "trigger_executions", ["executed_at"])
    op.create_index("ix_trigger_executions_task_id", "trigger_executions", ["task_id"])


def downgrade() -> None:
    """Drop all tables."""
    op.drop_table("trigger_executions")
    op.drop_table("triggers")
    op.drop_table("model_instances")
    op.drop_table("model_specs")
    op.drop_table("provider_configs")
    op.drop_table("provider_specs")
    op.drop_table("mcp_server_instances")
    op.drop_table("mcp_servers")
    op.drop_table("tasks")
    op.drop_table("agents")
