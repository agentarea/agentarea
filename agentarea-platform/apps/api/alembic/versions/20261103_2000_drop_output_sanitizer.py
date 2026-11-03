"""Safety rules no longer carry the removed output sanitizer toggle

The sanitizer rewrote model replies and tool results with regex redaction before the
model saw them, so the agent worked on data it could not trust, while the sandbox
kept every original. Every workspace baseline carried ``output_sanitizer: true``. The
key is dropped from stored rules, and a rule left with no toggle at all is deleted,
since it would be refused on its next edit as setting nothing.

Revision ID: 20261103_2000_drop_sanitizer
Revises: 20261103_1800_drop_ws_files
Create Date: 2026-11-03 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_2000_drop_sanitizer"
down_revision: str | None = "20261103_1800_drop_ws_files"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM policies WHERE effect = 'safety' "
            "AND params -> 'output_sanitizer' IS NOT NULL "
            "AND params - 'output_sanitizer' = '{}'::jsonb"
        )
    )
    bind.execute(
        sa.text(
            "UPDATE policies SET params = params - 'output_sanitizer' "
            "WHERE effect = 'safety' AND params -> 'output_sanitizer' IS NOT NULL"
        )
    )


def downgrade() -> None:
    # The toggle named a filter that no longer exists; nothing to restore.
    pass
