"""The catalog count indexes include the item's workspace (ADR-0044)

The two indexes that answer totals and facets from the index alone include
``registry_workspace_id``, so the visibility filter does not send them to the
heap. Built beside the old index and swapped, all concurrently: a plain CREATE
or DROP INDEX holds a lock every catalog read queues behind.

A revision of its own, after the schema change: the autocommit block commits
that revision's stamp first, so a run killed during the build resumes here.
Every step tolerates what an interrupted run left behind.

Revision ID: 20261019_1510_registry_count_ix
Revises: 20261019_1500_registry_scope
Create Date: 2026-10-19 15:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261019_1510_registry_count_ix"
down_revision: str | None = "20261019_1500_registry_scope"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COUNT_INDEXES = {
    "ix_registry_items_browse_name": (["registry_type", "sort_key", "id"], []),
    "ix_registry_items_browse_facets": (
        ["registry_type", "category"],
        ["protocol", "hosting", "pricing"],
    ),
}


def _recreate_count_indexes(*, with_workspace: bool) -> None:
    with op.get_context().autocommit_block():
        for name, (columns, include) in _COUNT_INDEXES.items():
            # Invalid when a build was interrupted; valid but unrenamed when the
            # run stopped after dropping the old index. Either is rebuilt.
            op.drop_index(
                f"{name}_next",
                table_name="registry_items",
                postgresql_concurrently=True,
                if_exists=True,
            )
            op.create_index(
                f"{name}_next",
                "registry_items",
                columns,
                postgresql_include=[
                    *include,
                    *(["registry_workspace_id"] if with_workspace else []),
                ],
                postgresql_where=sa.text("registry_active"),
                postgresql_concurrently=True,
            )
            op.drop_index(
                name, table_name="registry_items", postgresql_concurrently=True, if_exists=True
            )
            op.execute(f"ALTER INDEX {name}_next RENAME TO {name}")


def upgrade() -> None:
    _recreate_count_indexes(with_workspace=True)


def downgrade() -> None:
    _recreate_count_indexes(with_workspace=False)
