"""A harness client's runner executes agents' turns

A client of kind ``codex`` or ``claude`` can run a runner: the CLI on a
subscription, on some machine, executing the turns of agents that name the
client in ``agents.client_id`` (ADR-0051). The runner reports the CLI's models;
``default_model`` is the one turns use unless a task names another, and
``allow_domains`` the hosts the CLI's sandbox may reach. A runner's key is an
API key with ``client_id``: it reaches only that client's runner routes.

Revision ID: 20261107_1200_client_runner
Revises: 20261103_2000_drop_sanitizer
Create Date: 2026-11-07 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261107_1200_client_runner"
down_revision: str | None = "20261103_2000_drop_sanitizer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clients", sa.Column("models", postgresql.JSONB, nullable=True))
    op.add_column("clients", sa.Column("default_model", sa.String(255), nullable=True))
    op.add_column(
        "clients",
        sa.Column(
            "allow_domains",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_agents_client_id", "agents", ["client_id"])
    op.add_column(
        "api_keys",
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_api_keys_client_id", "api_keys", ["client_id"])


def downgrade() -> None:
    # A runner's key without its client would reach the whole workspace.
    op.execute("DELETE FROM api_keys WHERE client_id IS NOT NULL")
    op.drop_index("ix_api_keys_client_id", table_name="api_keys")
    op.drop_column("api_keys", "client_id")
    op.drop_index("ix_agents_client_id", table_name="agents")
    op.drop_column("agents", "client_id")
    op.drop_column("clients", "allow_domains")
    op.drop_column("clients", "default_model")
    op.drop_column("clients", "models")
