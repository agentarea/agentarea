"""Move built-in skills into the registry catalog and drop skills.source

ADR-003 (mirrors 20260606_0900 for agents): built-in/official skills stop being
materialized rows in ``skills`` with a platform workspace; they become
``registry_items`` (the catalog), and a tenant gets a real ``skills`` row only
on copy-on-write (carrying ``registry_item_id``). This migration:

1. converts existing official skills (``source = 'official'`` — the interim
   marker) into ``registry_items`` under a built-in ``skills`` registry,
   carrying the full skill definition in the item ``spec``,
2. de-materializes (deletes) those official skills from ``skills``, and
3. drops the now-unused ``skills.source`` column (built-in provenance is the
   registry catalog itself; the shared workspace read filter falls back to pure
   workspace scoping for skills once the column is gone).

Backfill is one-way: the de-materialization is not restored on downgrade
(``downgrade`` only re-adds the column).

Revision ID: 20260608_1100_skill_reg_prov
Revises: 20260608_1000_globalize_registry
Create Date: 2026-06-08 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_1100_skill_reg_prov"
down_revision: str = "20260608_1000_globalize_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Ensure a built-in 'skills' registry exists to own the catalog items.
    registry_id = conn.execute(
        sa.text(
            "SELECT id FROM registries "
            "WHERE registry_type = 'skills' AND name = 'Built-in Skills' LIMIT 1"
        )
    ).scalar()
    if registry_id is None:
        registry_id = conn.execute(
            sa.text(
                "INSERT INTO registries "
                "(id, name, registry_type, source_type, source_url, sync_mode, "
                " is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'Built-in Skills', "
                "'skills', 'url', 'builtin://skills', 'manual', true, now(), now()) "
                "RETURNING id"
            )
        ).scalar()

    # 2. Convert official skills into catalog items (idempotent on external_id).
    #    The spec carries the full skill definition needed by the copy-on-write
    #    fork (content, source refs, s3 package ref, network scope).
    conn.execute(
        sa.text(
            "INSERT INTO registry_items "
            "(id, registry_id, external_id, name, description, "
            " version, spec, tags, update_available, created_at, updated_at) "
            "SELECT gen_random_uuid(), :rid, s.slug, s.name, s.description, NULL, "
            "       jsonb_build_object("
            "         'name', s.name, 'description', s.description, "
            "         'source_type', s.source_type, 'content', s.content, "
            "         'source_url', s.source_url, 's3_path', s.s3_path, "
            "         'network_scope', s.network_scope), "
            "       '[]'::jsonb, false, now(), now() "
            "FROM skills s WHERE s.source = 'official' "
            "ON CONFLICT (registry_id, external_id) DO NOTHING"
        ),
        {"rid": registry_id},
    )

    # 3. De-materialize the official skills (they now live in the catalog).
    conn.execute(sa.text("DELETE FROM skills WHERE source = 'official'"))

    # 4. Drop the now-unused source column. Built-in provenance is the registry
    #    catalog; the base read filter falls back to pure workspace scoping.
    op.drop_column("skills", "source")


def downgrade() -> None:
    # One-way: de-materialized skills are not restored from the catalog.
    op.add_column(
        "skills",
        sa.Column(
            "source",
            sa.String(),
            nullable=False,
            server_default="workspace_custom",
        ),
    )
    op.alter_column("skills", "source", server_default=None)
