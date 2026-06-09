from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.utils.slug import generate_slug
from sqlalchemy import String, case, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.infrastructure.catalog_mcp_repository import (
    CatalogMcpItem,
    CatalogMcpRepository,
)


def _project_catalog_mcp_server(item: CatalogMcpItem) -> MCPServer:
    """Project a catalog MCP server item into a transient, read-only ``MCPServer``.

    The projected spec is NOT persisted. Its ``id`` is the catalog item's id so
    read paths can resolve it back to the registry item. Unlike agents/skills
    there is no copy-on-write: built-in specs are reference specs that users
    instantiate, not fork. ``registry_item_id`` is set so ``is_builtin`` holds.
    """
    spec = item.spec or {}
    conn_type = spec.get("connection_type", "url")
    docker_image_url = ""
    cmd_list = None
    if conn_type == "docker":
        docker_image_url = spec.get("image", "")
    elif conn_type == "command":
        docker_image_url = "agentarea/mcp-bridge:latest"
        command_str = spec.get("command", "")
        args = spec.get("args", []) or []
        if command_str:
            cmd_list = [command_str, *args]
    remote_url = spec.get("url") if conn_type == "url" else None
    raw_spec = spec.get("raw_spec") or spec
    env_schema = spec.get("env_schema")
    if not isinstance(env_schema, list):
        env_schema = []

    server = MCPServer(
        name=item.name,
        slug=generate_slug(item.name),
        description=item.description or "",
        version=item.version or "latest",
        docker_image_url=docker_image_url or None,
        tags=list(item.tags),
        status="active",
        env_schema=env_schema,
        cmd=cmd_list,
        remote_url=remote_url,
        registry_item_id=item.id,
        json_spec=raw_spec if isinstance(raw_spec, dict) else None,
        registry_url=item.registry_url,
    )
    server.id = UUID(item.id)
    # Transient projection is never persisted, so the DB-default timestamps never
    # fire (they run on INSERT). Carry the registry item's own non-null
    # timestamps so the response schema's required datetimes are populated.
    server.created_at = item.created_at
    server.updated_at = item.updated_at
    server.is_catalog = True  # type: ignore[attr-defined]
    return server


class MCPServerRepository(WorkspaceScopedRepository[MCPServer]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, MCPServer, user_context)

    def _get_catalog_repository(self) -> CatalogMcpRepository:
        """Get the read-only catalog (registry_items) repository for MCP specs."""
        return CatalogMcpRepository(session=self.session, user_context=self.user_context)

    @staticmethod
    def _filter_catalog_projection(
        server: MCPServer,
        *,
        status: str | None,
        is_public: bool | None,
        tag: str | None,
        search: str | None,
    ) -> bool:
        """Apply the same list filters to a catalog projection as the SQL query."""
        if status is not None and server.status != status:
            return False
        if is_public is not None and server.is_public != is_public:
            return False
        if tag is not None and tag not in (server.tags or []):
            return False
        if search is not None:
            term = search.lower()
            if (
                term not in (server.name or "").lower()
                and term not in (server.description or "").lower()
            ):
                return False
        return True

    def _build_list_query(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        tag: str | None = None,
        search: str | None = None,
        creator_scoped: bool = False,
        include_system: bool = True,
    ):
        """Build the base filtered query (without pagination) for list_servers."""
        query = select(self.model_class)

        if creator_scoped:
            query = query.where(self._get_creator_workspace_filter())
        else:
            query = query.where(self._get_workspace_filter())

        if status is not None:
            query = query.where(self.model_class.status == status)
        if is_public is not None:
            query = query.where(self.model_class.is_public == is_public)
        if tag is not None:
            # Filter tags in SQL using JSON containment (PostgreSQL @> operator)
            query = query.where(cast(self.model_class.tags, String).ilike(f'%"{tag}"%'))
        if search is not None:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    self.model_class.name.ilike(pattern),
                    self.model_class.description.ilike(pattern),
                )
            )

        return query

    async def list_servers(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        tag: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
        include_system: bool = True,
    ) -> tuple[list[MCPServer], int]:
        """List MCP servers with filtering, search, and pagination.

        Returns:
            Tuple of (servers, total_count)
        """
        base_query = self._build_list_query(
            status=status,
            is_public=is_public,
            tag=tag,
            search=search,
            creator_scoped=creator_scoped,
            include_system=include_system,
        )

        # Order: specs with icons first (json_spec has 'icons' key), then by name
        has_icons = case(
            (cast(self.model_class.json_spec, String).like('%"icons"%'), 0),
            else_=1,
        )
        query = base_query.order_by(has_icons, self.model_class.name)

        result = await self.session.execute(query)
        tenant_servers = list(result.scalars().all())

        # Merge read-only catalog projections (built-in specs live in the
        # registry catalog only, ADR-003). A catalog item already instantiated
        # by a tenant row carrying its registry_item_id is shadowed by that row.
        projections = await self._catalog_projections(
            tenant_servers,
            status=status,
            is_public=is_public,
            tag=tag,
            search=search,
        )

        merged = [*tenant_servers, *projections]
        total = len(merged)

        # Paginate the merged view in memory so catalog projections page
        # consistently alongside tenant rows.
        if offset > 0:
            merged = merged[offset:]
        if limit > 0:
            merged = merged[:limit]

        return merged, total

    async def _catalog_projections(
        self,
        tenant_servers: list[MCPServer],
        *,
        status: str | None,
        is_public: bool | None,
        tag: str | None,
        search: str | None,
    ) -> list[MCPServer]:
        """Project un-instantiated catalog MCP items as read-only specs."""
        catalog_items = await self._get_catalog_repository().list_items()
        shadowed = {
            str(s.registry_item_id) for s in tenant_servers if getattr(s, "registry_item_id", None)
        }
        projections: list[MCPServer] = []
        for item in catalog_items:
            if item.id in shadowed:
                continue
            server = _project_catalog_mcp_server(item)
            if self._filter_catalog_projection(
                server, status=status, is_public=is_public, tag=tag, search=search
            ):
                projections.append(server)
        return projections

    async def get_by_slug(self, slug: str) -> MCPServer | None:
        """Get MCP server by workspace-scoped slug."""
        query = (
            select(self.model_class)
            .where(self.model_class.slug == slug)
            .where(self._get_workspace_filter())
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_server_by_id(
        self,
        server_id: str,
        include_system: bool = True,
    ) -> MCPServer | None:
        """Get an MCP server by ID within accessible workspaces.

        Args:
            server_id: The server ID to look up
            include_system: Deprecated, kept for API compatibility. Access is now
                determined by accessible_workspaces on UserContext.

        Returns:
            The MCPServer if found, None otherwise
        """
        query = select(self.model_class).where(
            self.model_class.id == server_id,
            self._get_workspace_filter(),
        )

        result = await self.session.execute(query)
        server = result.scalar_one_or_none()
        if server is not None:
            return server

        # Fall back to a read-only catalog projection: built-in specs live in
        # the registry catalog only (ADR-003) and are not in mcp_servers.
        item = await self._get_catalog_repository().get_item(str(server_id))
        return _project_catalog_mcp_server(item) if item else None


class MCPServerInstanceRepository(WorkspaceScopedRepository[MCPServerInstance]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, MCPServerInstance, user_context)

    async def list_by_server_spec(
        self,
        server_spec_id: str,
        creator_scoped: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[MCPServerInstance]:
        """List instances by server spec ID within the current workspace."""
        return await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, server_spec_id=server_spec_id
        )

    async def list_by_status(
        self,
        status: str,
        creator_scoped: bool = False,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[MCPServerInstance]:
        """List instances by status within the current workspace."""
        return await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, status=status
        )
