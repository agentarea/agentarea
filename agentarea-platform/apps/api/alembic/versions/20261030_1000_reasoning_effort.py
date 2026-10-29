"""Reasoning effort: an agent's setting, and how each provider's API is asked for it

agents.reasoning_effort holds how hard the agent's model reasons before it answers
(minimal, low, medium, high); NULL leaves the model at its own default.

provider_specs.reasoning_param says how a request states that effort: OpenAI and
most compatible APIs take a top-level ``reasoning_effort``; OpenRouter takes
``reasoning: {"effort": ...}``, and so does the AgentArea gateway in front of it.

Revision ID: 20261030_1000_reasoning
Revises: 20261029_1800_output_cap
Create Date: 2026-10-30 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261030_1000_reasoning"
down_revision: str | None = "20261029_1800_output_cap"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("reasoning_effort", sa.String(16), nullable=True))
    op.add_column(
        "provider_specs",
        sa.Column(
            "reasoning_param", sa.String(16), nullable=False, server_default="reasoning_effort"
        ),
    )
    op.execute(
        sa.text(
            "UPDATE provider_specs SET reasoning_param = 'reasoning' "
            "WHERE provider_key IN ('openrouter', 'agentarea')"
        )
    )


def downgrade() -> None:
    op.drop_column("provider_specs", "reasoning_param")
    op.drop_column("agents", "reasoning_effort")
