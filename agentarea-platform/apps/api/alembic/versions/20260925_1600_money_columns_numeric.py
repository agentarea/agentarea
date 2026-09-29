"""Money columns are exact decimals, not binary floats

Per-token prices and wallet amounts were double precision: a ledger of ten
0.1 USD payments summed to 0.9999999999999999, and a price of 1e-9 USD per
token billed a million tokens at a value off by float rounding. Prices are
fractions of a cent, so they keep 12 decimal places; wallet amounts keep 6,
the precision of the USDC and Tempo units they are paid in.

The upgrade casts through ``text`` so each value becomes the shortest decimal
that round-trips its float, not the float's full binary expansion.

The price columns also lose their ``0`` server default. The application reads a
missing price as unknown and refuses to bill against it; the database default
turned a row inserted without one into an explicitly free model.

Revision ID: 20260925_1600_money_numeric
Revises: 20260925_1500_trg_channel_origin
Create Date: 2026-09-25 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260925_1600_money_numeric"
down_revision: str | None = "20260925_1500_trg_channel_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PRICE_COLUMNS = ("input_cost_per_token", "output_cost_per_token")
_COLUMNS = (
    ("model_specs", "input_cost_per_token", "NUMERIC(20, 12)"),
    ("model_specs", "output_cost_per_token", "NUMERIC(20, 12)"),
    ("agent_wallets", "service_budget_usd", "NUMERIC(18, 6)"),
    ("payment_records", "amount_usd", "NUMERIC(18, 6)"),
)


def upgrade() -> None:
    for table, column, numeric in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE {numeric} USING {column}::text::numeric"
        )
    for column in _PRICE_COLUMNS:
        op.execute(f"ALTER TABLE model_specs ALTER COLUMN {column} DROP DEFAULT")
    op.execute("ALTER TABLE agent_wallets ALTER COLUMN service_budget_usd SET DEFAULT 0")


def downgrade() -> None:
    for table, column, _ in _COLUMNS:
        op.execute(
            f"ALTER TABLE {table} ALTER COLUMN {column} "
            f"TYPE DOUBLE PRECISION USING {column}::double precision"
        )
    for column in _PRICE_COLUMNS:
        op.execute(f"ALTER TABLE model_specs ALTER COLUMN {column} SET DEFAULT 0.0")
    op.execute("ALTER TABLE agent_wallets ALTER COLUMN service_budget_usd SET DEFAULT 0.0")
