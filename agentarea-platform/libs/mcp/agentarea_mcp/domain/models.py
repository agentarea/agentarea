from typing import Any
from uuid import UUID

from agentarea_common.base.models import AuditMixin, BaseModel, WorkspaceScopedMixin
from agentarea_common.constants import PLATFORM_WORKSPACE_ID
from sqlalchemy import (
    JSON,
    Boolean,
    ColumnElement,
    String,
    UniqueConstraint,
    and_,
    column,
    exists,
    or_,
    table,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, declarative_base, mapped_column

Base = declarative_base()

# The registry catalog, named without importing the registry library.
_registry_items = table("registry_items", column("id"), column("registry_id"))
_registries = table("registries", column("id"), column("is_active"))


class MCPServer(BaseModel, WorkspaceScopedMixin, AuditMixin):
    """MCP Server model with workspace awareness and audit trail."""

    __tablename__ = "mcp_servers"

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_mcp_servers_workspace_slug"),
    )

    #: Governed by the authorization graph: creating one writes
    #: ``resource:<id>`` tuples so its creator can reach it afterwards.
    __graph_resource__ = True

    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String, nullable=False)
    docker_image_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    version: Mapped[str] = mapped_column(String, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="draft")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Environment variable schema - defines what env vars this server needs
    env_schema: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Custom command to override container CMD - useful for switching between stdio and HTTP modes
    cmd: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=None)
    # Remote URL for URL-type MCP servers (e.g. https://api.githubcopilot.com/mcp/)
    remote_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)
    # Provenance: links back to the registry catalog item this spec was installed from.
    # Column is a real Postgres uuid; bind as UUID (as_uuid=False makes asyncpg send a
    # VARCHAR, which Postgres rejects against the uuid column on insert).
    registry_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, default=None
    )
    # Raw ServerJSON spec from MCP registry — source of truth for icons, headers, variables, etc.
    json_spec: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True, default=None
    )
    # Source registry URL (e.g. https://registry.modelcontextprotocol.io)
    registry_url: Mapped[str | None] = mapped_column(String, nullable=True, default=None)

    @classmethod
    def workspace_visibility(cls, workspace_id: str) -> ColumnElement[bool]:
        """The workspace's own specs, plus every catalog mirror of an active registry.

        Built-in specs are readable by id from every workspace (ADR-003):
        reconcile mirrors them under the platform workspace with a
        ``registry_item_id``, and a mirror whose registry is deactivated
        disappears with it. A tenant's copy of a mirror keeps the
        ``registry_item_id`` but stays its own.
        """
        return or_(
            cls.workspace_id == workspace_id,
            and_(
                cls.workspace_id == PLATFORM_WORKSPACE_ID,
                cls.registry_item_id.is_not(None),
                exists().where(
                    _registry_items.c.id == cls.registry_item_id,
                    _registries.c.id == _registry_items.c.registry_id,
                    _registries.c.is_active.is_(True),
                ),
            ),
        )

    def __init__(
        self,
        name: str,
        description: str,
        slug: str | None = None,
        version: str = "1.0.0",
        docker_image_url: str | None = None,
        tags: list[str] | None = None,
        status: str = "draft",
        is_public: bool = False,
        env_schema: list[dict[str, Any]] | None = None,
        cmd: list[str] | None = None,
        remote_url: str | None = None,
        registry_item_id: UUID | str | None = None,
        json_spec: dict[str, Any] | None = None,
        registry_url: str | None = None,
        # Note: user_id and workspace_id are now handled by BaseModel
        **kwargs,
    ):
        super().__init__(**kwargs)  # Let BaseModel handle id, timestamps, user_id, workspace_id
        self.name = name
        if slug is not None:
            self.slug = slug
        self.description = description
        self.docker_image_url = docker_image_url
        self.version = version
        self.tags = tags or []
        self.status = status
        self.is_public = is_public
        self.env_schema = env_schema or []
        self.cmd = cmd
        self.remote_url = remote_url
        self.registry_item_id = (
            UUID(registry_item_id) if isinstance(registry_item_id, str) else registry_item_id
        )
        self.json_spec = json_spec
        self.registry_url = registry_url
