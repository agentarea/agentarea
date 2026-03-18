"""Add default_context_strategy to model_specs.

Revision ID: aa1ec6b67387
Revises: ff9ec6b67386
Create Date: 2026-03-18

"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "aa1ec6b67387"
down_revision = "ff9ec6b67386"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "model_specs",
        sa.Column("default_context_strategy", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_specs", "default_context_strategy")
