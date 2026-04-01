"""enrich model_specs with costs and capabilities

Revision ID: hh1_enrich_model_specs
Revises: gg1_add_icon_to_mcp_servers
Create Date: 2026-03-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "hh1_enrich_model_specs"
down_revision: str | None = "0235e2291c9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_specs",
        sa.Column("max_output_tokens", sa.Integer(), nullable=True, server_default="4096"),
    )
    op.add_column(
        "model_specs",
        sa.Column("input_cost_per_token", sa.Float(), nullable=True, server_default="0.0"),
    )
    op.add_column(
        "model_specs",
        sa.Column("output_cost_per_token", sa.Float(), nullable=True, server_default="0.0"),
    )
    op.add_column(
        "model_specs",
        sa.Column("supports_function_calling", sa.Boolean(), nullable=True, server_default="false"),
    )
    op.add_column(
        "model_specs",
        sa.Column("supports_vision", sa.Boolean(), nullable=True, server_default="false"),
    )
    op.add_column(
        "model_specs",
        sa.Column("supports_reasoning", sa.Boolean(), nullable=True, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("model_specs", "supports_reasoning")
    op.drop_column("model_specs", "supports_vision")
    op.drop_column("model_specs", "supports_function_calling")
    op.drop_column("model_specs", "output_cost_per_token")
    op.drop_column("model_specs", "input_cost_per_token")
    op.drop_column("model_specs", "max_output_tokens")
