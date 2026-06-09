"""Add agents.registry_item_id and move built-in agents into the registry catalog

ADR-003: built-in/official agents stop being materialized rows in ``agents``
with a platform workspace; they become ``registry_items`` (the catalog), and a
tenant gets a real ``agents`` row only on copy-on-write (carrying
``registry_item_id``). This migration:

1. adds ``agents.registry_item_id`` (forward provenance link), and
2. converts existing official agents (``source = 'official'`` — the interim
   marker) into ``registry_items`` under a built-in ``agents`` registry, then
   de-materializes them from ``agents``.

Backfill is one-way: the de-materialization is not restored on downgrade
(``downgrade`` only drops the column).

Revision ID: 20260606_0900_agent_reg_prov
Revises: 20260605_1100_unify_gov_policy
Create Date: 2026-06-06 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0900_agent_reg_prov"
down_revision: str = "20260605_1100_unify_gov_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Forward provenance link on tenant agents (matches the ORM column).
    op.add_column("agents", sa.Column("registry_item_id", sa.String(), nullable=True))
    op.create_index("ix_agents_registry_item_id", "agents", ["registry_item_id"])

    # 2. Ensure a built-in 'agents' registry exists to own the catalog items.
    registry_id = conn.execute(
        sa.text(
            "SELECT id FROM registries "
            "WHERE registry_type = 'agents' AND workspace_id = 'platform' LIMIT 1"
        )
    ).scalar()
    if registry_id is None:
        registry_id = conn.execute(
            sa.text(
                "INSERT INTO registries "
                "(id, workspace_id, created_by, name, registry_type, source_type, "
                " source_url, sync_mode, is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'platform', 'platform', 'Built-in Agents', "
                "'agents', 'url', 'builtin://agents', 'manual', true, now(), now()) "
                "RETURNING id"
            )
        ).scalar()

    # 3. Convert official agents into catalog items (idempotent on external_id).
    conn.execute(
        sa.text(
            "INSERT INTO registry_items "
            "(id, workspace_id, created_by, registry_id, external_id, name, description, "
            " version, spec, tags, update_available, created_at, updated_at) "
            "SELECT gen_random_uuid(), 'platform', 'platform', :rid, a.id::text, a.name, "
            "       a.description, NULL, "
            "       jsonb_build_object("
            "         'id', a.id::text, 'instruction', a.instruction, 'model_id', a.model_id, "
            "         'tools', a.tools, 'events_config', a.events_config, "
            "         'planning', a.planning, 'description', a.description, "
            "         'agent_type', a.agent_type), "
            "       '[]'::jsonb, false, now(), now() "
            "FROM agents a WHERE a.source = 'official' "
            "ON CONFLICT (registry_id, external_id) DO NOTHING"
        ),
        {"rid": registry_id},
    )

    # 4. De-materialize the official agents (they now live in the catalog).
    conn.execute(sa.text("DELETE FROM agents WHERE source = 'official'"))


def downgrade() -> None:
    # One-way: de-materialized agents are not restored from the catalog.
    op.drop_index("ix_agents_registry_item_id", table_name="agents")
    op.drop_column("agents", "registry_item_id")
