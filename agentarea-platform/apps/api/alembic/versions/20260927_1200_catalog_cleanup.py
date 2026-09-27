"""catalog cleanup: retire the legacy MCP rows, fold skill categories, title connections

Four things made /explore hard to read:

1. "Built-in MCP Servers" (builtin://mcp_servers) holds 8.5k rows copied from
   the old ``mcp_servers`` table in 20260608_1200. Nothing syncs it any more and
   the system MCP catalog republishes the same servers, so every server showed
   up twice. Its rows also carry ``recommendation_rank`` 0 and no category, so
   under the default "recommended" sort they outranked the curated catalog
   (ranked 0..n) -- the unfiltered connections list opened on an alphabetical
   run of legacy entries, while any category filter hid them. The registry is
   deactivated, not deleted: installs keep resolving, the rows just leave the
   gallery.
2. Skills carried whatever category their source invented (74 values, half
   used once). They fold into the closed set in
   ``catalog_facets.SKILL_CATEGORIES``; the mapping below is a frozen copy.
3. Connections sorted by their registry id (``ai.agentarea.catalog/...``);
   they now sort by the title the gallery shows.
4. The 124k bulk-imported skills (``skills-shards``) predate recommendation
   ranks and all sit at 0, so "recommended" was alphabetical: the gallery
   opened on "0000", "001 polish and pu...". The hand-curated skills registry
   now outranks the bulk mirror, and bulk skills rank by their GitHub-star
   bucket until the next sync writes real per-source ranks.

Revision ID: 20260927_1200_catalog_cleanup
Revises: 20260926_1200_drop_events_cfg
Create Date: 2026-09-27
"""

# Every interpolated value below is a module constant, never input.
# ruff: noqa: S608

from collections.abc import Sequence

from alembic import op

revision: str = "20260927_1200_catalog_cleanup"
down_revision: str | None = "20260926_1200_drop_events_cfg"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_MCP_REGISTRY = "builtin://mcp_servers"
CURATED_SKILLS = "%/registry/system/skills.json"
BULK_SKILLS = "%/registry/system/skills-shards/%"
# Lower sorts first; registries default to 100.
CURATED_PRIORITY = 10
_STAR_BUCKET_RANK = (("stars:1000+", 1), ("stars:100+", 2), ("stars:10+", 3), ("stars:1+", 4))
UNRATED_RANK = 5

_GROUPS: dict[str, tuple[str, ...]] = {
    "development": (
        "development",
        "development-tools",
        "engineering",
        "programming-languages",
        "language",
        "framework",
        "bash",
        "string",
        "core",
        "foundation",
        "extended",
        "applied",
        "github-integration",
        "github-skills",
    ),
    "testing": (
        "testing",
        "quality",
        "performance",
        "testing-methodologies",
        "specialized-testing",
        "test",
    ),
    "devops": ("devops", "platform", "system", "local-ai-infrastructure"),
    "data": (
        "data",
        "analysis",
        "analysis-methods",
        "research-analysis",
        "story-analysis",
        "forensics",
    ),
    "agents": (
        "agent",
        "agents",
        "agent-coordination",
        "orchestration",
        "context-management",
        "ai-llm",
        "ai-ml",
        "generation",
        "artifact-generation",
        "skills",
        "meta",
        "adb-meta-automation",
    ),
    "design": ("design", "creative"),
    "documents": ("documents", "document-processing", "docs", "writing"),
    "security": ("security", "security-compliance", "security-operations", "war-room"),
    "marketing": ("marketing",),
    "product": (
        "product",
        "planning",
        "project",
        "business",
        "business-monetization",
        "c-level",
    ),
    "productivity": ("productivity", "workflow", "personal-development", "utility", "travel"),
    "integration": (
        "integration",
        "api",
        "messaging",
        "communication",
        "technical-integration",
        "wix-extensions",
    ),
    "gaming": ("gaming",),
}

# The source category, as the facet derivation reads it from the tags.
_SOURCE_CATEGORY = (
    "(SELECT lower(btrim(substring(t.value from 10))) "
    " FROM jsonb_array_elements_text(ri.tags) AS t(value) "
    " WHERE t.value LIKE 'category:%' LIMIT 1)"
)


def _mapping_values() -> str:
    rows = [f"('{raw}', '{group}')" for group, raws in _GROUPS.items() for raw in raws]
    return ", ".join(rows)


def upgrade() -> None:
    op.execute(
        f"UPDATE registries SET is_active = false, updated_at = now() "
        f"WHERE source_url = '{LEGACY_MCP_REGISTRY}'"
    )
    op.execute(
        f"UPDATE registry_items SET registry_active = false WHERE registry_id IN "
        f"(SELECT id FROM registries WHERE source_url = '{LEGACY_MCP_REGISTRY}')"
    )

    op.execute(
        f"""
        UPDATE registry_items ri
        SET category = CASE
            WHEN src.raw IS NULL OR src.raw = '' THEN NULL
            ELSE coalesce(m.grp, 'other')
        END
        FROM (SELECT ri.id, {_SOURCE_CATEGORY} AS raw
              FROM registry_items ri WHERE ri.registry_type = 'skills') AS src
        LEFT JOIN (VALUES {_mapping_values()}) AS m(raw, grp) ON m.raw = src.raw
        WHERE ri.id = src.id
        """
    )

    op.execute(
        f"UPDATE registries SET recommendation_priority = {CURATED_PRIORITY} "
        f"WHERE registry_type = 'skills' AND source_url LIKE '{CURATED_SKILLS}'"
    )
    op.execute(
        f"UPDATE registry_items SET registry_priority = {CURATED_PRIORITY} WHERE registry_id IN "
        f"(SELECT id FROM registries WHERE registry_type = 'skills' "
        f" AND source_url LIKE '{CURATED_SKILLS}')"
    )
    buckets = " ".join(
        f"WHEN tags @> '[\"{tag}\"]'::jsonb THEN {rank}" for tag, rank in _STAR_BUCKET_RANK
    )
    op.execute(
        f"UPDATE registry_items SET recommendation_rank = CASE {buckets} ELSE {UNRATED_RANK} END "
        f"WHERE registry_type = 'skills' AND recommendation_rank = 0 AND registry_id IN "
        f"(SELECT id FROM registries WHERE source_url LIKE '{BULK_SKILLS}')"
    )

    # Mirrors catalog_facets._connection_title.
    op.execute(
        """
        UPDATE registry_items ri
        SET sort_key = left(lower(coalesce(
            NULLIF(ri.spec->'raw_spec'->>'title', ''),
            NULLIF(ri.spec->>'title', ''),
            NULLIF(btrim(regexp_replace(regexp_replace(ri.name, '^.*/', ''), '[-_]+', ' ', 'g')), ''),
            ri.name
        )), 255)
        WHERE ri.registry_type = 'mcp_servers'
        """
    )


def downgrade() -> None:
    op.execute(
        f"UPDATE registries SET recommendation_priority = 100 "
        f"WHERE registry_type = 'skills' AND source_url LIKE '{CURATED_SKILLS}'"
    )
    op.execute(
        f"UPDATE registry_items SET registry_priority = 100 WHERE registry_id IN "
        f"(SELECT id FROM registries WHERE registry_type = 'skills' "
        f" AND source_url LIKE '{CURATED_SKILLS}')"
    )
    op.execute(
        f"UPDATE registry_items SET recommendation_rank = 0 WHERE registry_type = 'skills' "
        f"AND registry_id IN (SELECT id FROM registries WHERE source_url LIKE '{BULK_SKILLS}')"
    )
    op.execute(
        f"UPDATE registries SET is_active = true, updated_at = now() "
        f"WHERE source_url = '{LEGACY_MCP_REGISTRY}'"
    )
    op.execute(
        f"UPDATE registry_items SET registry_active = true WHERE registry_id IN "
        f"(SELECT id FROM registries WHERE source_url = '{LEGACY_MCP_REGISTRY}')"
    )
    op.execute(
        """
        UPDATE registry_items ri
        SET category = (SELECT NULLIF(substring(t.value from 10), '')
                        FROM jsonb_array_elements_text(ri.tags) AS t(value)
                        WHERE t.value LIKE 'category:%' LIMIT 1)
        WHERE ri.registry_type = 'skills'
        """
    )
    op.execute(
        "UPDATE registry_items SET sort_key = lower(name) WHERE registry_type = 'mcp_servers'"
    )
