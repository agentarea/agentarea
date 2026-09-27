from collections.abc import Collection
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import (
    WorkspaceScopedRepository,
    as_record_ids,
)
from agentarea_common.utils.slug import generate_slug
from sqlalchemy import String, case, cast, func, or_, select, text
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

    def _build_list_query(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        tag: str | None = None,
        search: str | None = None,
        creator_scoped: bool = False,
        include_system: bool = True,
        ids: set[str] | None = None,
        spec_ids: Collection[str] | None = None,
    ):
        """Build the base filtered query (without pagination) for list_servers."""
        query = select(self.model_class)

        if creator_scoped:
            query = query.where(self._get_creator_workspace_filter())
        else:
            query = query.where(self._get_workspace_filter())

        if ids is not None:
            # What the authorization graph says this caller may read, applied in
            # SQL so the returned total matches the rows they actually get.
            query = query.where(self.model_class.id.in_(as_record_ids(ids)))
        if spec_ids is not None:
            query = query.where(self.model_class.id.in_(as_record_ids(set(spec_ids))))

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

        # Hide specs backed by a deactivated registry (e.g. an unpublished
        # catalog mirror). Show a spec only if it is user-created (no registry
        # link) or its backing registry is active. Without this the list would
        # surface every reconciled catalog row, including deactivated mirrors.
        query = query.where(
            text(
                "(mcp_servers.registry_item_id IS NULL OR EXISTS ("
                "SELECT 1 FROM registry_items ri "
                "JOIN registries r ON r.id = ri.registry_id "
                "WHERE ri.id = mcp_servers.registry_item_id AND r.is_active))"
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
        ids: set[str] | None = None,
        spec_ids: Collection[str] | None = None,
    ) -> tuple[list[MCPServer], int]:
        """List MCP server specs: tenant rows first, then read-only catalog projections.

        Built-in specs live in the registry catalog only (ADR-003), and a catalog
        item a tenant row already instantiates is shadowed by that row. Both
        halves are filtered and paged in SQL: the catalog is global and large, so
        it must never be materialized per request.

        ``ids`` narrows the tenant half to what the caller may read; catalog items
        are platform data with no ownership tuples, so it leaves them alone.
        ``spec_ids`` asks for exactly those specs, tenant rows and catalog items
        alike.

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
            ids=ids,
            spec_ids=spec_ids,
        )
        tenant_total = (
            await self.session.execute(select(func.count()).select_from(base_query.subquery()))
        ).scalar_one()

        # Order: specs with icons first (json_spec has 'icons' key), then by name
        has_icons = case(
            (cast(self.model_class.json_spec, String).like('%"icons"%'), 0),
            else_=1,
        )
        page_query = (
            base_query.order_by(has_icons, self.model_class.name, self.model_class.id)
            .offset(offset)
            .limit(limit)
        )
        tenant_page = list((await self.session.execute(page_query)).scalars().all())

        # A projection is always an active, non-public spec.
        if (status is not None and status != "active") or is_public:
            return tenant_page, tenant_total

        instantiated = await self.session.execute(
            base_query.with_only_columns(self.model_class.registry_item_id).where(
                self.model_class.registry_item_id.is_not(None)
            )
        )
        catalog_items, catalog_total = await self._get_catalog_repository().list_page(
            limit=max(0, limit - len(tenant_page)),
            offset=max(0, offset - tenant_total),
            exclude_item_ids=[str(item_id) for item_id in instantiated.scalars().all()],
            tag=tag,
            search=search,
            item_ids=spec_ids,
        )
        projections = [_project_catalog_mcp_server(item) for item in catalog_items]
        return [*tenant_page, *projections], tenant_total + catalog_total

    async def get_by_slug(self, slug: str) -> MCPServer | None:
        """Get MCP server by workspace-scoped slug."""
        query = (
            select(self.model_class)
            .where(self.model_class.slug == slug)
            .where(self._get_workspace_filter())
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def resolve_unique_slug(self, name: str) -> str:
        """Workspace-unique slug for ``name``: ``base``, then ``base-2``..``base-999``.

        Single source of truth for the NOT NULL ``slug`` column - every persisting
        create path must route slugs through here so none can forget it.
        """
        base = generate_slug(name)
        if await self.get_by_slug(base) is None:
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if await self.get_by_slug(candidate) is None:
                return candidate
        raise ValueError(f"Exhausted collision suffixes (-2..-999) for slug base '{base}'")

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

        # Built-in catalog specs are globally readable by id, not workspace-scoped
        # (ADR-003). Reconcile mirrors them into mcp_servers under the platform
        # workspace with a registry_item_id; resolve those across workspaces, but
        # only catalog mirrors (registry_item_id IS NOT NULL) backed by an active
        # registry — never another tenant's private custom spec.
        catalog_mirror = select(self.model_class).where(
            self.model_class.id == server_id,
            text(
                "EXISTS (SELECT 1 FROM registry_items ri "
                "JOIN registries r ON r.id = ri.registry_id "
                "WHERE ri.id = mcp_servers.registry_item_id AND r.is_active)"
            ),
        )
        server = (await self.session.execute(catalog_mirror)).scalar_one_or_none()
        if server is not None:
            return server

        # Fall back to a read-only catalog projection: built-in specs may live in
        # the registry catalog only (ADR-003), addressed by their registry-item id.
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
