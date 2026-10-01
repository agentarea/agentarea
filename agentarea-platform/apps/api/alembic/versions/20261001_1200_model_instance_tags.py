"""model_instances.tags: labels the operator puts on platform models

The platform model a new agent starts on is the one tagged ``default``. Tags are
data written by the operator from the LLMProviderConfig resource, so changing the
default is an edit in git rather than a redeploy. Tenant instances keep ``[]``.

Revision ID: 20261001_1200_model_inst_tags
Revises: 20260930_1000_task_conversation
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261001_1200_model_inst_tags"
down_revision: str | None = "20260930_1000_task_conversation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_instances",
        sa.Column(
            "tags",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("model_instances", "tags")
