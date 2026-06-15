"""Index registry_items on (registry_id, lower(name)) for catalog ordering.

The Explore catalog lists registry items one registry at a time, ordered
case-insensitively by name (``RegistryItemRepository.list_by_registry``:
``WHERE registry_id = :id ORDER BY lower(name)``). A composite index whose
trailing key is the ``lower(name)`` expression lets Postgres return rows already
in order for a given registry, so paginated / infinite-scroll reads avoid a
full sort on every page.

Revision ID: 20260615_1200_reg_item_name_idx
Revises: 20260608_1200_mcp_model_reg_prov
Create Date: 2026-06-15 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260615_1200_reg_item_name_idx"
down_revision: str = "20260608_1200_mcp_model_reg_prov"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_NAME = "ix_registry_items_registry_id_lower_name"


def upgrade() -> None:
    op.create_index(
        _INDEX_NAME,
        "registry_items",
        ["registry_id", sa.text("lower(name)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="registry_items")
