"""Registry domain models — external source registries and their cached catalog items.

Supports multiple entity types via registry_type:
  - "mcp_servers" → syncs into mcp_servers table
  - "skills" → syncs into skills table

Entity-specific details (connection_type, source_type, etc.) live in spec JSONB.
"""

from datetime import datetime
from typing import Any

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class Registry(BaseModel, WorkspaceScopedMixin):
    """A configured external source of entity definitions.

    registry_type determines what gets created on sync:
        - "mcp_servers": creates MCPServer specs
        - "skills": creates Skill records

    source_type determines how to fetch:
        - "url": JSON or YAML bundle at a URL
        - "github": GitHub repo with a known registry format
        - "api": REST API endpoint
    """

    __tablename__ = "registries"

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

    def __init__(
        self,
        name: str,
        registry_type: str,
        source_type: str,
        source_url: str,
        description: str | None = None,
        sync_mode: str = "manual",
        is_active: bool = True,
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
        self.last_synced_at = None
        self.last_sync_error = None
        self.item_count = 0


class RegistryItem(BaseModel, WorkspaceScopedMixin):
    """A cached catalog entry synced from a Registry.

    On first sync, each item auto-creates the target entity.
    On re-sync, version changes are flagged but not auto-applied.

    Entity-specific details live in spec JSONB:
        mcp_servers: spec.connection_type, spec.image, spec.command, etc.
        skills: spec.source_type, spec.content, spec.source_url, etc.
    """

    __tablename__ = "registry_items"

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

    def __init__(
        self,
        registry_id: str,
        external_id: str,
        name: str,
        description: str | None = None,
        version: str | None = None,
        spec: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.registry_id = registry_id
        self.external_id = external_id
        self.name = name
        self.description = description
        self.version = version
        self.spec = spec or {}
        self.tags = tags or []
        self.installed_entity_id = None
        self.update_available = False
        self.installed_version = None
