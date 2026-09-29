"""registry_items.in_source: hide catalog items their source stopped publishing

The platform never deletes catalog rows, so an item a source dropped stayed
browsable forever: on RU 441 connections the published catalog no longer
carries, among them the old id of a renamed server shown as a second "Sentry"
card beside the new one. Sync now records whether the source still publishes
each item, and `registry_active` means "registry active AND still in the
source". Every row starts in the source; the next sync of each registry
corrects it.

Revision ID: 20260929_1400_item_in_source
Revises: 20260929_1000_openapi_url_vars
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260929_1400_item_in_source"
down_revision: str | None = "20260929_1000_openapi_url_vars"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "registry_items",
        sa.Column("in_source", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.execute(
        "UPDATE registry_items ri SET registry_active = r.is_active "
        "FROM registries r WHERE r.id = ri.registry_id"
    )
    op.drop_column("registry_items", "in_source")
