"""Registry domain models — external source registries and their cached catalog items.

Supports multiple entity types via registry_type:
  - "mcp_servers" → syncs into mcp_servers table
  - "skills" → syncs into skills table

Entity-specific details (connection_type, source_type, etc.) live in spec JSONB.
"""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

# Registry ordering weight for the ``recommended`` catalog sort: lower comes
# first. A curated system catalog and an opt-in bulk/community mirror both hold
# rank-0 items, so without a per-source weight the mirror's first entry would
# interleave with the curated front page.
DEFAULT_REGISTRY_PRIORITY = 100


class Registry(BaseModel):
    """A configured external source of entity definitions.

    Global catalog infrastructure — NOT workspace-scoped. Built-in/official
    content lives here once and is readable by every tenant.

    registry_type determines what gets created on sync:
        - "mcp_servers": creates MCPServer specs
        - "skills": creates Skill records

    source_type determines how to fetch:
        - "url": JSON or YAML bundle at a URL
        - "github": GitHub repo with a known registry format
        - "api": REST API endpoint
        - "managed": items are published through the platform catalog API
    """

    __tablename__ = "registries"
    # Reconcile finds a configured source by name. Without this, two writers
    # racing on a first sync each saw "no such registry" and created one: prod
    # carried a second copy of most skill shards and of the MCP catalog, every
    # item listed twice.
    __table_args__ = (UniqueConstraint("name", name="uq_registries_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    registry_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    sync_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = name
        self.description = description
        self.registry_type = registry_type
        self.source_type = source_type
        self.source_url = source_url
        self.sync_mode = sync_mode
        self.is_active = is_active
        self.recommendation_priority = recommendation_priority
        self.last_synced_at = None
        self.last_sync_error = None
        self.item_count = 0


class RegistryItem(BaseModel):
    """A cached catalog entry synced from a Registry.

    Global catalog infrastructure — NOT workspace-scoped.

    On first sync, each item auto-creates the target entity.
    On re-sync, version changes are flagged but not auto-applied.

    Entity-specific details live in spec JSONB:
        mcp_servers: spec.connection_type, spec.image, spec.command, etc.
        skills: spec.source_type, spec.content, spec.source_url, etc.
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
        # Totals and facet counts: carries every column their filters read, so
        # they are counted from the index without visiting a row.
        Index(
            "ix_registry_items_browse_facets",
            "registry_type",
            "category",
            postgresql_include=["protocol"],
            postgresql_where=text("registry_active"),
        ),
        # Free-text search is `ILIKE '%term%'`, which no btree can answer.
        Index(
            "ix_registry_items_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        Index(
            "ix_registry_items_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
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
        *,
        registry_type: str,
        registry_priority: int,
        registry_active: bool,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.registry_id = registry_id
        self.registry_type = registry_type
        self.registry_priority = registry_priority
        self.registry_active = registry_active
        self.protocol = protocol
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
