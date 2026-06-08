"""Move built-in MCP server specs + model specs into the catalog and drop source

ADR-003 (mirrors 20260606_0900 for agents and 20260608_1100 for skills): the
built-in/official reference specs ``mcp_servers`` and ``model_specs`` stop being
materialized rows with a platform workspace; they become ``registry_items`` (the
catalog) read globally by ``CatalogMcpRepository`` / ``CatalogModelSpecRepository``.

Unlike agents/skills there is NO copy-on-write fork here: these are reference
specs that users instantiate via ``mcp_server_instances`` / ``model_instances``,
they do not edit the spec. So this migration only de-materializes the built-in
rows; user-custom specs (source != 'official') stay in their entity tables.

This migration:

1. converts existing official ``mcp_servers`` (``source = 'official'``) into
   ``registry_items`` under a built-in ``mcp_servers`` registry, carrying the
   full spec (connection details + raw json_spec) in the item ``spec``;
2. converts existing official ``model_specs`` into ``registry_items`` under a
   built-in ``llm_models`` registry, carrying provider_key + model fields;
3. de-materializes (deletes) those official rows; and
4. drops the now-unused ``source`` column from ALL remaining tables that still
   carry it: ``mcp_servers``, ``model_specs``, ``agents``,
   ``mcp_server_instances``, ``provider_configs``. After this, no table has a
   ``source`` column and the base read filter is pure workspace scoping.

Backfill is one-way: de-materialization is not restored on downgrade
(``downgrade`` only re-adds the columns).

Revision ID: 20260608_1200_mcp_model_reg_prov
Revises: 20260608_1100_skill_reg_prov
Create Date: 2026-06-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260608_1200_mcp_model_reg_prov"
down_revision: str = "20260608_1100_skill_reg_prov"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_TABLES = (
    "mcp_servers",
    "model_specs",
    "agents",
    "mcp_server_instances",
    "provider_configs",
)


def _ensure_registry(conn, name: str, registry_type: str, source_url: str) -> str:
    registry_id = conn.execute(
        sa.text(
            "SELECT id FROM registries "
            "WHERE registry_type = :rt AND name = :name LIMIT 1"
        ),
        {"rt": registry_type, "name": name},
    ).scalar()
    if registry_id is None:
        registry_id = conn.execute(
            sa.text(
                "INSERT INTO registries "
                "(id, name, registry_type, source_type, source_url, sync_mode, "
                " is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :name, :rt, 'url', :url, 'manual', "
                "true, now(), now()) RETURNING id"
            ),
            {"name": name, "rt": registry_type, "url": source_url},
        ).scalar()
    return registry_id


def upgrade() -> None:
    conn = op.get_bind()

    # 1. MCP servers: official rows -> catalog items. The spec carries the
    #    connection details and the raw ServerJSON (icons/headers/variables).
    mcp_registry_id = _ensure_registry(
        conn, "Built-in MCP Servers", "mcp_servers", "builtin://mcp_servers"
    )
    conn.execute(
        sa.text(
            "INSERT INTO registry_items "
            "(id, registry_id, external_id, name, description, "
            " version, spec, tags, update_available, created_at, updated_at) "
            "SELECT gen_random_uuid(), :rid, m.slug, m.name, m.description, m.version, "
            "       COALESCE(m.json_spec, '{}'::jsonb) "
            "         || jsonb_build_object('registry_url', m.registry_url, "
            "                               'env_schema', COALESCE(m.env_schema, '[]'::jsonb), "
            "                               'cmd', m.cmd, 'remote_url', m.remote_url, "
            "                               'docker_image_url', m.docker_image_url), "
            "       COALESCE(m.tags, '[]'::jsonb), false, now(), now() "
            "FROM mcp_servers m WHERE m.source = 'official' "
            "ON CONFLICT (registry_id, external_id) DO NOTHING"
        ),
        {"rid": mcp_registry_id},
    )
    conn.execute(sa.text("DELETE FROM mcp_servers WHERE source = 'official'"))

    # 2. Model specs: official rows -> catalog items. The spec carries the
    #    provider_key (resolved from provider_specs) + the model fields the
    #    read-side projection needs.
    model_registry_id = _ensure_registry(
        conn, "Built-in Models", "llm_models", "builtin://llm_models"
    )
    conn.execute(
        sa.text(
            "INSERT INTO registry_items "
            "(id, registry_id, external_id, name, description, "
            " version, spec, tags, update_available, created_at, updated_at) "
            "SELECT gen_random_uuid(), :rid, ps.provider_key || '/' || ms.model_name, "
            "       ms.display_name, ms.description, NULL, "
            "       jsonb_build_object("
            "         'provider_key', ps.provider_key, 'model_name', ms.model_name, "
            "         'context_window', ms.context_window, "
            "         'max_output_tokens', ms.max_output_tokens, "
            "         'input_cost_per_token', ms.input_cost_per_token, "
            "         'output_cost_per_token', ms.output_cost_per_token, "
            "         'supports_function_calling', ms.supports_function_calling, "
            "         'is_active', ms.is_active), "
            "       '[]'::jsonb, false, now(), now() "
            "FROM model_specs ms "
            "JOIN provider_specs ps ON ps.id = ms.provider_spec_id "
            "WHERE ms.source = 'official' "
            "ON CONFLICT (registry_id, external_id) DO NOTHING"
        ),
        {"rid": model_registry_id},
    )
    conn.execute(sa.text("DELETE FROM model_specs WHERE source = 'official'"))

    # 3. Drop the now-unused source column everywhere. Built-in provenance is the
    #    registry catalog; the base read filter is pure workspace scoping.
    for table in _SOURCE_TABLES:
        op.drop_column(table, "source")


def downgrade() -> None:
    # One-way: de-materialized specs are not restored from the catalog.
    for table in _SOURCE_TABLES:
        op.add_column(
            table,
            sa.Column(
                "source",
                sa.String(),
                nullable=False,
                server_default="workspace_custom",
            ),
        )
        op.alter_column(table, "source", server_default=None)
