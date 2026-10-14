"""agents.answer_check: the agent's own final-answer check setting

Null leaves the check off unless a governance safety rule turns it on.

Revision ID: 20261013_1800_agent_answer_check
Revises: 20261013_1700_cached_input_price
Create Date: 2026-10-13 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261013_1800_agent_answer_check"
down_revision: str | None = "20261013_1700_cached_input_price"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("answer_check", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "answer_check")
