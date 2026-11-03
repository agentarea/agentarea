"""provider_specs.cache_breakpoints: the provider's API takes prompt-cache breakpoints

True when the API accepts Anthropic-style ``cache_control`` breakpoints on message
content and hands them to the models that cache only what a request marks (Claude,
Qwen). OpenRouter does, and so does the AgentArea gateway in front of it. The
catalog (llm-providers.json) carries it for entries that state it.

Revision ID: 20261103_1200_cache_breakpoints
Revises: 20261101_1800_mcp_tool_ids
Create Date: 2026-11-03 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_1200_cache_breakpoints"
down_revision: str | None = "20261101_1800_mcp_tool_ids"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_specs",
        sa.Column("cache_breakpoints", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.execute(
        sa.text(
            "UPDATE provider_specs SET cache_breakpoints = true "
            "WHERE provider_key IN ('openrouter', 'agentarea')"
        )
    )


def downgrade() -> None:
    op.drop_column("provider_specs", "cache_breakpoints")
