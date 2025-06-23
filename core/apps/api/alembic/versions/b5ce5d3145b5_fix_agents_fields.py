"""fix agents fields.

Revision ID: b5ce5d3145b5
Revises: 8954caa2c0f6
Create Date: 2025-05-04 21:58:23.775503

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5ce5d3145b5"
down_revision: str | None = "8954caa2c0f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("agents", sa.Column("description", sa.String(), nullable=True))
    op.add_column("agents", sa.Column("model_id", sa.String(), nullable=True))
    op.add_column("agents", sa.Column("tools_config", sa.JSON(), nullable=True))
    op.add_column("agents", sa.Column("events_config", sa.JSON(), nullable=True))
    op.add_column("agents", sa.Column("planning", sa.String(), nullable=True))
    op.drop_column("agents", "capabilities")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("agents", sa.Column("capabilities", sa.JSON(), nullable=False))
    op.drop_column("agents", "planning")
    op.drop_column("agents", "events_config")
    op.drop_column("agents", "tools_config")
    op.drop_column("agents", "model_id")
    op.drop_column("agents", "description")
