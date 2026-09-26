"""Drop agents.events_config: triggers are their own entity

The agent form wrote "event subscriptions" into ``agents.events_config``, but
nothing ever turned them into schedules, webhooks or channels, so an agent set
to run on a schedule never ran. Triggers live in the ``triggers`` table and are
now created alongside the agent. Existing values held no working configuration
(empty event types on every row checked), so they are not carried over.

Revision ID: 20260926_1200_drop_events_cfg
Revises: 20260925_1800_catalog_browse
Create Date: 2026-09-26 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260926_1200_drop_events_cfg"
down_revision: str | None = "20260925_1800_catalog_browse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("agents", "events_config")


def downgrade() -> None:
    op.add_column("agents", sa.Column("events_config", sa.JSON(), nullable=True))
