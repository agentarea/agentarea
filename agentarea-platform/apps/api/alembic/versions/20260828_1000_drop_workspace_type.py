"""Drop workspaces.type — the fact already lives in the id

``type`` only ever held 'personal' or 'shared', and both values are implied by
the row itself: a workspace auto-provisioned for one user reuses that user's id
(``id == owner_user_id``), an explicitly created one gets a fresh uuid. Nothing
in the backend read the column — ``is_personal`` had no callers and
``WORKSPACE_TYPE_SHARED`` was referenced only where it was written — so it was a
second copy of a fact that could only ever drift from the id it described.

Reversible: the downgrade recreates the column and derives every value back.

Revision ID: 20260828_1000_drop_ws_type
Revises: 20260830_0100_catalog_facets
Create Date: 2026-08-28 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260828_1000_drop_ws_type"
down_revision: str | None = "20260830_0100_catalog_facets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("workspaces", "type")


def downgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("type", sa.String(length=20), nullable=False, server_default="personal"),
    )
    op.execute(
        "UPDATE workspaces SET type = CASE WHEN id = owner_user_id "
        "THEN 'personal' ELSE 'shared' END"
    )
