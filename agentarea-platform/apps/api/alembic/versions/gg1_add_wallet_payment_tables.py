"""Add agent_wallets and payment_records tables.

Revision ID: gg1_add_wallet_payment_tables
Revises: ff9ec6b67386
Create Date: 2026-03-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "gg1_add_wallet_payment_tables"
down_revision = "ff9ec6b67386"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_wallets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("agent_id", UUID(as_uuid=True), sa.ForeignKey("agents.id"), nullable=False, index=True),
        sa.Column("wallet_type", sa.String(), nullable=False),
        sa.Column("x402_config", sa.JSON(), nullable=True),
        sa.Column("mpp_config", sa.JSON(), nullable=True),
        sa.Column("credentials_secret_id", sa.String(), nullable=True),
        sa.Column("service_budget_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("service_budget_period", sa.String(), nullable=False, server_default="execution"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("agent_id", "workspace_id", name="uq_agent_wallet_per_workspace"),
    )

    op.create_table(
        "payment_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False, index=True),
        sa.Column("created_by", sa.String(255), nullable=False, index=True),
        sa.Column("wallet_id", UUID(as_uuid=True), sa.ForeignKey("agent_wallets.id"), nullable=False, index=True),
        sa.Column("agent_id", sa.String(), nullable=False, index=True),
        sa.Column("execution_id", sa.String(), nullable=False, index=True),
        sa.Column("protocol", sa.String(), nullable=False),
        sa.Column("amount_usd", sa.Float(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("tx_hash", sa.String(), nullable=True),
        sa.Column("tool_name", sa.String(), nullable=False),
        sa.Column("tool_call_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("protocol_metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("payment_records")
    op.drop_table("agent_wallets")
