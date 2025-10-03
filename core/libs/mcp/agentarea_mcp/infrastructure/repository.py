from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance


class MCPServerRepository(WorkspaceScopedRepository[MCPServer]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, MCPServer, user_context)

    async def list_servers(
        self,
        status: str | None = None,
        is_public: bool | None = None,
        tag: str | None = None,
        limit: int = 100,
        offset: int = 0,
        creator_scoped: bool = False,
    ) -> list[MCPServer]:
        """List MCP servers with filtering."""
        filters = {}
        if status is not None:
            filters["status"] = status
        if is_public is not None:
            filters["is_public"] = is_public

        # Note: tag filtering with JSON arrays is complex and may need custom implementation
        # For now, we'll handle basic filters through the base class
        servers = await self.list_all(
            creator_scoped=creator_scoped, limit=limit, offset=offset, **filters
        )

        # Apply tag filtering manually if needed
        if tag is not None:
            servers = [s for s in servers if tag in (s.tags or [])]

        return servers

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
