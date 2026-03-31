"""Add ON DELETE CASCADE to wallet FK constraints.

Revision ID: gg2_add_wallet_fk_cascades
Revises: gg1_add_wallet_payment_tables
Create Date: 2026-03-29
"""

from alembic import op

revision = "gg2_add_wallet_fk_cascades"
down_revision = "gg1_add_wallet_payment_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # agent_wallets.agent_id → agents.id CASCADE
    op.drop_constraint("agent_wallets_agent_id_fkey", "agent_wallets", type_="foreignkey")
    op.create_foreign_key(
        "agent_wallets_agent_id_fkey",
        "agent_wallets",
        "agents",
        ["agent_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # payment_records.wallet_id → agent_wallets.id CASCADE
    op.drop_constraint("payment_records_wallet_id_fkey", "payment_records", type_="foreignkey")
    op.create_foreign_key(
        "payment_records_wallet_id_fkey",
        "payment_records",
        "agent_wallets",
        ["wallet_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Revert payment_records FK
    op.drop_constraint("payment_records_wallet_id_fkey", "payment_records", type_="foreignkey")
    op.create_foreign_key(
        "payment_records_wallet_id_fkey",
        "payment_records",
        "agent_wallets",
        ["wallet_id"],
        ["id"],
    )

    # Revert agent_wallets FK
    op.drop_constraint("agent_wallets_agent_id_fkey", "agent_wallets", type_="foreignkey")
    op.create_foreign_key(
        "agent_wallets_agent_id_fkey",
        "agent_wallets",
        "agents",
        ["agent_id"],
        ["id"],
    )
