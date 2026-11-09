"""Reasoning levels are catalog data; an agent may set a reasoning token budget

provider_specs.reasoning_efforts and model_specs.reasoning_efforts list the
reasoning levels a provider's models (or one model) take; the model's list wins,
and with neither the level goes to the provider as given. Both come from the
catalog (llm-providers.json, llm-models.json, the LLMProviderConfig resource).

agents.reasoning_max_tokens is a reasoning token budget, the alternative to a
level; NULL leaves the model at its own default.

Revision ID: 20261030_1200_reasoning_data
Revises: 20261030_1000_reasoning
Create Date: 2026-10-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261030_1200_reasoning_data"
down_revision: str | None = "20261030_1000_reasoning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("provider_specs", sa.Column("reasoning_efforts", postgresql.JSONB, nullable=True))
    op.add_column("model_specs", sa.Column("reasoning_efforts", postgresql.JSONB, nullable=True))
    op.add_column("agents", sa.Column("reasoning_max_tokens", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "reasoning_max_tokens")
    op.drop_column("model_specs", "reasoning_efforts")
    op.drop_column("provider_specs", "reasoning_efforts")
