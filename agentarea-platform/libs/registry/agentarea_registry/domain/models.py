"""Registry domain models — external source registries and their cached catalog items.

Supports multiple entity types via registry_type:
  - "mcp_servers" → syncs into mcp_servers table
  - "skills" → syncs into skills table

Entity-specific details (connection_type, source_type, etc.) live in spec JSONB.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# Registry ordering weight for the ``recommended`` catalog sort: lower comes
# first. A curated system catalog and an opt-in bulk/community mirror both hold
# rank-0 items, so without a per-source weight the mirror's first entry would
# interleave with the curated front page.
DEFAULT_REGISTRY_PRIORITY = 100

# ADR-0044. A platform registry is seen by every workspace; a workspace registry
# only by the workspace whose admin added it.
REGISTRY_SCOPES = ("platform", "workspace")
# mirror: content is copied when the index syncs; upstream: only the index is
# kept and content is fetched on first install of a version.
REGISTRY_MODES = ("mirror", "upstream")
# A sync of any other type materializes platform-wide entities, so a workspace
# registry may hold only these catalog-only types.
WORKSPACE_REGISTRY_TYPES = ("skills", "agents")


class Registry(BaseModel):
    """A configured external source of entity definitions.

    Not workspace-scoped through WorkspaceScopedMixin: a ``platform`` registry
    is read by every tenant, a ``workspace`` registry only by ``workspace_id``,
    and the catalog reads filter on that (ADR-0044).

    registry_type determines what gets created on sync:
        - "mcp_servers": creates MCPServer specs
        - "skills": creates Skill records

    source_type determines how to fetch:
        - "url": JSON or YAML bundle at a URL
        - "github": a GitHub repository whose folders are skills
        - "api": REST API endpoint
        - "managed": items are published through the platform catalog API

    A "github" source is ``source_url`` ``owner/repo`` read at ``source_ref``
    under ``source_path``: every folder holding a SKILL.md is one skill.
    """

    __tablename__ = "registries"
    # Reconcile finds a configured source by name. Without this, two writers
    # racing on a first sync each saw "no such registry" and created one: prod
    # carried a second copy of most skill shards and of the MCP catalog, every
    # item listed twice.
    # Names are unique per scope: a workspace's registry may share a name with
    # the platform's or another workspace's.
    __table_args__ = (
        Index(
            "uq_registries_platform_name",
            "name",
            unique=True,
            postgresql_where=text("scope = 'platform'"),
        ),
        Index(
            "uq_registries_workspace_name",
            "workspace_id",
            "name",
            unique=True,
            postgresql_where=text("scope = 'workspace'"),
        ),
        CheckConstraint("scope IN ('platform', 'workspace')", name="ck_registries_scope"),
        CheckConstraint("mode IN ('mirror', 'upstream')", name="ck_registries_mode"),
        CheckConstraint(
            "trust IN ('official', 'verified', 'community', 'private')",
            name="ck_registries_trust",
        ),
        CheckConstraint(
            "(scope = 'platform' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL "
            "AND registry_type IN ('skills', 'agents'))",
            name="ck_registries_scope_workspace",
        ),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    registry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    sync_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The source's ETag (an index URL) or head commit (a GitHub repository) as
    # of the last applied sync; an unchanged one is skipped.
    source_etag: Mapped[str | None] = mapped_column(Text, nullable=True)
    # GitHub sources: the branch, tag or commit to read, and the folder under
    # which every directory holding a SKILL.md is a skill.
    source_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(
        String(16), nullable=False, default="platform", server_default="platform"
    )
    workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="mirror", server_default="mirror"
    )
    trust: Mapped[str] = mapped_column(
        String(16), nullable=False, default="official", server_default="official"
    )
    # The workspace secret a sync authenticates with; resolved at sync time,
    # never copied here. The database holds the RESTRICT foreign key to
    # encrypted_secrets; it is not declared here because this library does not
    # depend on the one that maps that table.
    credentials_secret_ref: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_REGISTRY_PRIORITY
    )

    def __init__(
        self,
        name: str,
        registry_type: str,
        source_type: str,
        source_url: str,
        description: str | None = None,
        sync_mode: str = "manual",
        is_active: bool = True,
        recommendation_priority: int = DEFAULT_REGISTRY_PRIORITY,
        scope: str = "platform",
        workspace_id: str | None = None,
        mode: str = "mirror",
        trust: str = "official",
        credentials_secret_ref: UUID | None = None,
        source_ref: str | None = None,
        source_path: str | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.scope = scope
        self.workspace_id = workspace_id
        self.mode = mode
        self.trust = trust
        self.credentials_secret_ref = credentials_secret_ref
        self.source_ref = source_ref
        self.source_path = source_path
        self.description = description
        self.registry_type = registry_type
        self.source_type = source_type
        self.source_url = source_url
        self.sync_mode = sync_mode
        self.is_active = is_active
        self.recommendation_priority = recommendation_priority
        self.last_synced_at = None
        self.last_sync_error = None
        self.source_etag = None
        self.item_count = 0


class RegistryItem(BaseModel):
    """A cached catalog entry synced from a Registry.

    Global catalog infrastructure — NOT workspace-scoped.

    On first sync, each item auto-creates the target entity.
    On re-sync, version changes are flagged but not auto-applied.

    Entity-specific details live in spec JSONB:
        mcp_servers: spec.connection_type, spec.image, spec.command, etc.
        skills: spec.source (a GitHub pointer, ADR-0044) or an inline spec.content,
            spec.source_type, spec.source_url, etc.
    """

    __tablename__ = "registry_items"
    # Every browse query is bounded by `registry_type`, reads only items of
    # active registries, and is served by one of these, so /explore costs a
    # page of index entries rather than a scan of the whole catalog (~300k rows,
    # each carrying ~1 KB of spec). The ordering indexes mirror CATALOG_SORTS
    # column for column -- an index that does not match the ORDER BY exactly
    # cannot stop the sort.
    __table_args__ = (
        Index(
            "ix_registry_items_browse_recommended",
            "registry_type",
            text("featured DESC"),
            "registry_priority",
            "recommendation_rank",
            "sort_key",
            "id",
            postgresql_where=text("registry_active"),
        ),
        Index(
            "ix_registry_items_browse_category_recommended",
            "registry_type",
            "category",
            text("featured DESC"),
            "registry_priority",
            "recommendation_rank",
            "sort_key",
            "id",
            postgresql_where=text("registry_active"),
        ),
        Index(
            "ix_registry_items_browse_name",
            "registry_type",
            "sort_key",
            "id",
            postgresql_include=["registry_workspace_id"],
            postgresql_where=text("registry_active"),
        ),
        Index(
            "ix_registry_items_browse_category_name",
            "registry_type",
            "category",
            "sort_key",
            "id",
            postgresql_where=text("registry_active"),
        ),
        # Totals and facet counts: carries every column their filters read (the
        # workspace visibility filter too), so they are counted from the index
        # without visiting a row.
        Index(
            "ix_registry_items_browse_facets",
            "registry_type",
            "category",
            postgresql_include=["protocol", "hosting", "pricing", "registry_workspace_id"],
            postgresql_where=text("registry_active"),
        ),
    )

    registry_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("registries.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    installed_entity_id: Mapped[str | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    update_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    installed_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Browse facets, derived from the heterogeneous spec/tags above at sync time
    # (see application.catalog_facets.derive_facets). Denormalized so the
    # catalog can be filtered, ordered and counted in SQL: every registry type
    # hides its category somewhere different, and the title the UI shows is
    # often not `name`, so neither is reachable from a portable query.
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_key: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    featured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "mcp" or "api" for the connections catalog, NULL for every other type.
    protocol: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # "vendor" or "agentarea" for MCP connections, NULL otherwise.
    hosting: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # "paid", "own_key" or "free" for connections, NULL otherwise.
    pricing: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Curation order within the owning registry: lower comes first. Sources are
    # already authored best-first (the curated skills artifact is ordered by
    # GitHub stars, the connection artifact leads with official integrations),
    # and that order is the only usefulness signal the catalog has -- without
    # persisting it, browsing collapses to alphabetical.
    recommendation_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Copies of the owning registry's type, weight and active flag. Browse
    # filters and orders on them; while they lived only on `registries`, no
    # index on this table could produce the catalog order, so every page sorted
    # the whole type. RegistryItemRepository.create stamps them and
    # RegistryRepository.update keeps them in step.
    registry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    registry_priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=DEFAULT_REGISTRY_PRIORITY
    )
    registry_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # NULL for a platform registry's item, which every workspace sees; else the
    # only workspace that may see or install it.
    registry_workspace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registry_trust: Mapped[str] = mapped_column(
        String(16), nullable=False, default="official", server_default="official"
    )
    # Whether the source still publishes this item. The platform never deletes
    # catalog rows (installs point at them), so an item a source dropped used to
    # stay browsable forever -- the old id of a renamed server showed up as a
    # second card beside the new one. Sync keeps this in step, and
    # `registry_active` (what browse and its indexes filter on) is "registry
    # active AND still in the source".
    in_source: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    def __init__(
        self,
        registry_id: str,
        external_id: str,
        name: str,
        description: str | None = None,
        version: str | None = None,
        spec: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        category: str | None = None,
        sort_key: str | None = None,
        featured: bool = False,
        recommendation_rank: int = 0,
        protocol: str | None = None,
        hosting: str | None = None,
        pricing: str | None = None,
        *,
        registry_type: str,
        registry_priority: int,
        registry_active: bool,
        registry_workspace_id: str | None = None,
        registry_trust: str = "official",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.registry_id = registry_id
        self.registry_workspace_id = registry_workspace_id
        self.registry_trust = registry_trust
        self.registry_type = registry_type
        self.registry_priority = registry_priority
        self.registry_active = registry_active
        self.protocol = protocol
        self.hosting = hosting
        self.pricing = pricing
        self.external_id = external_id
        self.name = name
        self.description = description
        self.version = version
        self.spec = spec or {}
        self.tags = tags or []
        self.installed_entity_id = None
        self.update_available = False
        self.installed_version = None
        self.category = category
        # Never leave the ordering column empty: a caller that skips facet
        # derivation gets plain case-folded name ordering rather than a catalog
        # that pages in arbitrary order.
        self.sort_key = sort_key if sort_key is not None else name.casefold()
        self.featured = featured
        self.recommendation_rank = recommendation_rank


class RegistryItemInstall(BaseModel):
    """Workspace-scoped materialization state for a global registry item."""

    __tablename__ = "registry_item_installs"
    __table_args__ = (
        UniqueConstraint(
            "registry_item_id",
            "workspace_id",
            name="uq_registry_item_installs_item_workspace",
        ),
    )

    registry_item_id: Mapped[str] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("registry_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    installed_entity_id: Mapped[str] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    installed_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
