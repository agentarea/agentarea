"""signup_attributions: which channel brought each sign-up (ADR-0047)

One row per identity, written by Kratos's after-registration hook: the method, and
the first touch of the landing visit (channel, referrer host, landing host and path
pattern, utm_*). No email, no IP. created_at is when the identity was created.

Revision ID: 20261028_1200_signup_attribution
Revises: 20261021_1200_installation
Create Date: 2026-10-28 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261028_1200_signup_attribution"
down_revision: str | None = "20261021_1200_installation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signup_attributions",
        sa.Column("identity_id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("method", sa.String(16), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("referrer_host", sa.String(64), nullable=True),
        sa.Column("landing_host", sa.String(64), nullable=True),
        sa.Column("landing_path", sa.String(64), nullable=True),
        sa.Column("utm_source", sa.String(64), nullable=True),
        sa.Column("utm_medium", sa.String(64), nullable=True),
        sa.Column("utm_campaign", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("signup_attributions")
