"""add trigger tables.

Revision ID: d7f8e9a0b2c3
Revises: c6d7e8f9a0b1
Create Date: 2025-01-21 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7f8e9a0b2c3"
down_revision: str | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create triggers table
    op.create_table(
        "triggers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        
        # Basic trigger fields
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, default=""),
        sa.Column("agent_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_type", sa.String(50), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("task_parameters", sa.JSON(), nullable=False, default={}),
        sa.Column("conditions", sa.JSON(), nullable=False, default={}),
        sa.Column("created_by", sa.String(255), nullable=False),
        
        # Rate limiting and safety
        sa.Column("max_executions_per_hour", sa.Integer(), nullable=False, default=60),
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
        
        # Predefined webhook configurations
        sa.Column("telegram_config", sa.JSON(), nullable=True),
        sa.Column("slack_config", sa.JSON(), nullable=True),
        sa.Column("github_config", sa.JSON(), nullable=True),
    )
    
    # Create trigger_executions table
    op.create_table(
        "trigger_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        
        # Basic execution fields
        sa.Column(
            "trigger_id",
            UUID(as_uuid=True),
            sa.ForeignKey("triggers.id", ondelete="CASCADE"),
            nullable=False
        ),
        sa.Column("executed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("task_id", UUID(as_uuid=True), nullable=True),
        sa.Column("execution_time_ms", sa.Integer(), nullable=False, default=0),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("trigger_data", sa.JSON(), nullable=False, default={}),
        
        # Temporal workflow tracking
        sa.Column("workflow_id", sa.String(255), nullable=True),
        sa.Column("run_id", sa.String(255), nullable=True),
    )
    
    # Create indexes for performance
    op.create_index("idx_triggers_agent_id", "triggers", ["agent_id"])
    op.create_index("idx_triggers_type", "triggers", ["trigger_type"])
    op.create_index("idx_triggers_active", "triggers", ["is_active"])
    op.create_index("idx_triggers_webhook_id", "triggers", ["webhook_id"])
    op.create_index("idx_triggers_next_run", "triggers", ["next_run_time"])
    
    op.create_index("idx_trigger_executions_trigger_id", "trigger_executions", ["trigger_id"])
    op.create_index("idx_trigger_executions_status", "trigger_executions", ["status"])
    op.create_index("idx_trigger_executions_executed_at", "trigger_executions", ["executed_at"])
    op.create_index("idx_trigger_executions_task_id", "trigger_executions", ["task_id"])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index("idx_trigger_executions_task_id")
    op.drop_index("idx_trigger_executions_executed_at")
    op.drop_index("idx_trigger_executions_status")
    op.drop_index("idx_trigger_executions_trigger_id")
    
    op.drop_index("idx_triggers_next_run")
    op.drop_index("idx_triggers_webhook_id")
    op.drop_index("idx_triggers_active")
    op.drop_index("idx_triggers_type")
    op.drop_index("idx_triggers_agent_id")
    
    # Drop tables
    op.drop_table("trigger_executions")
    op.drop_table("triggers")