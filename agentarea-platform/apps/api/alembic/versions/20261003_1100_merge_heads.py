"""Merge the client-toolsets and A2A-agent-address heads

Revision ID: 20261003_1100_merge_heads
Revises: 20261002_1200_a2a_agent_addrs, 20261001_1800_client_toolsets
Create Date: 2026-10-03 11:00:00.000000
"""

from collections.abc import Sequence

revision: str = "20261003_1100_merge_heads"
down_revision: tuple[str, str] = (
    "20261002_1200_a2a_agent_addrs",
    "20261001_1800_client_toolsets",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
