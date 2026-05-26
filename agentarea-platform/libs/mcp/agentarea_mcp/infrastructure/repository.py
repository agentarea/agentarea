from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance


class MCPServerRepository(WorkspaceScopedRepository[MCPServer]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, MCPServer, user_context)

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

        # Count total matching records
        count_query = select(func.count()).select_from(base_query.subquery())
        total = (await self.session.execute(count_query)).scalar_one()

        # Order: specs with icons first (json_spec has 'icons' key), then by name
        has_icons = case(
            (cast(self.model_class.json_spec, String).like('%"icons"%'), 0),
            else_=1,
        )
        query = base_query.order_by(has_icons, self.model_class.name)

        # Apply pagination
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        servers = list(result.scalars().all())

        return servers, total

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
        return result.scalar_one_or_none()

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[MCPServer]:
        """Get MCP servers by workspace ID with pagination.

        Note: This method is deprecated. Use list_servers() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_servers()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_servers(limit=limit, offset=offset)

    async def create_server(self, entity: MCPServer) -> MCPServer:
        """Create a new MCP server from domain entity.

        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the server entity
        server_data = {
            "id": entity.id,
            "name": entity.name,
            "description": entity.description,
            "status": entity.status,
            "is_public": entity.is_public,
            "tags": entity.tags,
            "config": getattr(entity, "config", None),
            "created_at": entity.created_at,
            "updated_at": entity.updated_at,
        }

        # Remove None values and system fields that will be auto-populated
        server_data = {k: v for k, v in server_data.items() if v is not None}
        server_data.pop("created_at", None)
        server_data.pop("updated_at", None)

        return await self.create(**server_data)

    async def update_server(self, entity: MCPServer) -> MCPServer:
        """Update an existing MCP server from domain entity.

        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the server entity
        server_data = {
            "name": entity.name,
            "description": entity.description,
            "status": entity.status,
            "is_public": entity.is_public,
            "tags": entity.tags,
            "config": getattr(entity, "config", None),
        }

        # Remove None values
        server_data = {k: v for k, v in server_data.items() if v is not None}

        updated_server = await self.update(entity.id, **server_data)
        return updated_server or entity


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

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[MCPServerInstance]:
        """Get MCP server instances by workspace ID with pagination.

        Note: This method is deprecated. Use list_all() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_all()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_all(limit=limit, offset=offset)
