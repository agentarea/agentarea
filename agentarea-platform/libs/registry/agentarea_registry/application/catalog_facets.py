"""Browsable dimensions derived from a registry item.

The catalog is heterogeneous: every registry type buries its category in a
different corner of ``spec``/``tags``, and the title the UI shows is often not
the ``name`` column (skill ids carry provenance the UI strips). Browsing the
catalog means filtering, sorting and counting by exactly those two things, so
they are derived once here and persisted as plain columns -- SQL can then do
the paging, and the client stops re-sorting a partially-loaded list.

This mirrors ``normalize()`` in the webapp
(agentarea-webapp/src/app/(main)/bundles/components/catalog-data.ts). The two
must agree: the server orders by ``sort_key``, the client renders ``title``.
"""

import re
from typing import Any, Literal, NamedTuple, get_args

FEATURED_TAG = "featured"
_CATEGORY_TAG_PREFIX = "category:"
_REPO_TAG_PREFIX = "repo:"

# Connections are not all MCP: a catalog entry is either an MCP server (reached
# over a transport -- url/command/docker) or a plain HTTP API described by an
# OpenAPI document. The distinction is what the gallery lets you filter on, and
# `spec.connection_type` is where every parser records it.
OPENAPI_CONNECTION_TYPE = "openapi"
CatalogProtocol = Literal["mcp", "api"]
# Facet order: the vocabulary is closed, so derive it rather than restating it.
CATALOG_PROTOCOLS: tuple[CatalogProtocol, ...] = get_args(CatalogProtocol)
# Only the connections catalog has a protocol dimension; every other registry
# type holds one kind of thing.
PROTOCOL_REGISTRY_TYPE = "mcp_servers"


class ItemFacets(NamedTuple):
    """Derived, persisted browse dimensions for one catalog item."""

    category: str | None
    sort_key: str
    featured: bool
    protocol: CatalogProtocol | None


def _mapping(value: Any) -> dict[str, Any]:
    """A mapping or an empty one -- sources are external and shapes vary."""
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    """Non-empty string or None (matches the client's `str()` helper)."""
    return value if isinstance(value, str) and value else None


def _tag_value(tags: list[Any], prefix: str) -> str | None:
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            return _text(tag[len(prefix) :])
    return None


def _prettify_skill_name(name: str, repo: str | None) -> str:
    """The human part of a registry skill id.

    Ids look like ``action-creator--owner-repo--<hash>``: everything before the
    first ``--`` is the name, the rest is provenance. Some sources instead glue
    the repo on with a single dash (``frontend-design-anthropics-claude-code``);
    strip that using the repo tag. Casing is left alone -- the caller folds it.
    """
    head = name.split("--")[0]
    if head == name and repo:
        repo_slug = re.sub(r"[^a-z0-9]+", "-", repo, flags=re.IGNORECASE).lower()
        if repo_slug and head.lower().endswith(f"-{repo_slug}"):
            head = head[: len(head) - len(repo_slug) - 1]
    return re.sub(r"[-_]+", " ", head).strip()


# Skills arrive with whatever category their source invented: 74 distinct values
# in the current import, half of them used by a single skill ("war-room",
# "wix-extensions"). A facet list that long is unbrowsable, so skill categories
# fold into a closed set. Keys are the source spellings; anything unlisted is
# "other".
SKILL_CATEGORIES: dict[str, str] = {
    **dict.fromkeys(
        (
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
        "development",
    ),
    **dict.fromkeys(
        (
            "testing",
            "quality",
            "performance",
            "testing-methodologies",
            "specialized-testing",
            "test",
        ),
        "testing",
    ),
    **dict.fromkeys(("devops", "platform", "system", "local-ai-infrastructure"), "devops"),
    **dict.fromkeys(
        (
            "data",
            "analysis",
            "analysis-methods",
            "research-analysis",
            "story-analysis",
            "forensics",
        ),
        "data",
    ),
    **dict.fromkeys(
        (
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
        "agents",
    ),
    **dict.fromkeys(("design", "creative"), "design"),
    **dict.fromkeys(("documents", "document-processing", "docs", "writing"), "documents"),
    **dict.fromkeys(
        ("security", "security-compliance", "security-operations", "war-room"), "security"
    ),
    "marketing": "marketing",
    **dict.fromkeys(
        ("product", "planning", "project", "business", "business-monetization", "c-level"),
        "product",
    ),
    **dict.fromkeys(
        ("productivity", "workflow", "personal-development", "utility", "travel"),
        "productivity",
    ),
    **dict.fromkeys(
        (
            "integration",
            "api",
            "messaging",
            "communication",
            "technical-integration",
            "wix-extensions",
        ),
        "integration",
    ),
    "gaming": "gaming",
}
SKILL_FALLBACK_CATEGORY = "other"


def skill_category(raw: str | None) -> str:
    """The closed-set category for a skill's source category."""
    return SKILL_CATEGORIES.get((raw or "").strip().lower(), SKILL_FALLBACK_CATEGORY)


def _connection_title(name: str, spec: dict[str, Any]) -> str:
    """What a person calls an MCP server.

    ``name`` is a registry id (``ai.agentarea.catalog/ahrefs``,
    ``io.github.owner/repo-mcp``): unique, but the reverse-DNS namespace makes
    every curated entry read the same. The server's own ``title`` wins; without
    one, the part after the namespace is the name.
    """
    raw = _mapping(spec.get("raw_spec"))
    title = _text(raw.get("title")) or _text(spec.get("title"))
    if title:
        return title
    # A package entry's id carries the package ("…/npm/@sentry/mcp-server");
    # the server it belongs to is the name.
    server = _text(raw.get("name")) or name
    tail = server.rsplit("/", 1)[-1]
    return re.sub(r"[-_]+", " ", tail).strip() or server


def _category(registry_type: str, spec: dict[str, Any], tags: list[Any]) -> str | None:
    if registry_type == "bundles":
        return _text(_mapping(spec.get("metadata")).get("category"))
    if registry_type == "agents":
        # Catalog agents carry domain tags (support, engineering, data...); the
        # first one is the category, same as the cards show.
        return _text(tags[0]) if tags else None
    if registry_type == "skills":
        source = _tag_value(tags, _CATEGORY_TAG_PREFIX)
        return skill_category(source) if source else None
    if registry_type == "mcp_servers":
        raw_meta = _mapping(_mapping(spec.get("raw_spec")).get("metadata"))
        return _text(raw_meta.get("agentarea:category"))
    # llm_providers / llm_models have no category dimension in the gallery.
    return None


def _title(registry_type: str, name: str, spec: dict[str, Any], tags: list[Any]) -> str:
    if registry_type == "bundles":
        return _text(spec.get("display_name")) or _text(spec.get("name")) or name
    if registry_type == "skills":
        explicit = _text(spec.get("display_name"))
        if explicit:
            return explicit
        original_name = _text(spec.get("original_name"))
        return (
            _prettify_skill_name(
                original_name or name,
                None if original_name else _tag_value(tags, _REPO_TAG_PREFIX),
            )
            or name
        )
    if registry_type == "mcp_servers":
        return _connection_title(name, spec)
    return name


def _protocol(registry_type: str, spec: dict[str, Any]) -> CatalogProtocol | None:
    if registry_type != PROTOCOL_REGISTRY_TYPE:
        return None
    # An entry that never recorded a connection_type is an MCP server: managed
    # publications predate the field.
    return "api" if spec.get("connection_type") == OPENAPI_CONNECTION_TYPE else "mcp"


def derive_facets(
    registry_type: str,
    name: str,
    spec: dict[str, Any] | None,
    tags: list[Any] | None,
) -> ItemFacets:
    """Category, sort key, featured flag and protocol for one catalog item."""
    spec = _mapping(spec)
    tags = tags if isinstance(tags, list) else []
    return ItemFacets(
        category=_category(registry_type, spec, tags),
        # The column is VARCHAR(255); a source title can be longer.
        sort_key=_title(registry_type, name, spec, tags).casefold()[:255],
        featured=FEATURED_TAG in tags,
        protocol=_protocol(registry_type, spec),
    )


def apply_facets(item: Any, registry_type: str) -> Any:
    """Write the derived facets onto a registry item, in place.

    Used by the re-sync path, where ``name``/``spec``/``tags`` have just been
    overwritten from the source and the derived columns must follow.
    """
    facets = derive_facets(registry_type, item.name, item.spec, item.tags)
    item.category = facets.category
    item.sort_key = facets.sort_key
    item.featured = facets.featured
    item.protocol = facets.protocol
    return item
