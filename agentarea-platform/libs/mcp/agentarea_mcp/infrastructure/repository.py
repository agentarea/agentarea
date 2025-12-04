from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import or_, select
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
        include_system: bool = True,
    ) -> list[MCPServer]:
        """List MCP servers with filtering.

        By default, includes public servers from the "system" workspace (built-in servers)
        in addition to the user's workspace servers.

        Args:
            status: Filter by status
            is_public: Filter by public flag
            tag: Filter by tag
            limit: Maximum number of records
            offset: Number of records to skip
            creator_scoped: Only return servers created by current user
            include_system: Include public servers from system workspace (default True)
        """
        # Build custom query to include system public servers
        query = select(self.model_class)

        if creator_scoped:
            # Only user's own servers in their workspace
            query = query.where(self._get_creator_workspace_filter())
        elif include_system:
            # Include both workspace servers AND public system servers
            query = query.where(
                or_(
                    self.model_class.workspace_id == self.user_context.workspace_id,
                    (self.model_class.workspace_id == "system") & self.model_class.is_public,
                )
            )
        else:
            # Only workspace servers
            query = query.where(self._get_workspace_filter())

        # Apply additional filters
        if status is not None:
            query = query.where(self.model_class.status == status)
        if is_public is not None:
            query = query.where(self.model_class.is_public == is_public)

        # Apply pagination
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        servers = list(result.scalars().all())

        # Apply tag filtering manually if needed
        if tag is not None:
            servers = [s for s in servers if tag in (s.tags or [])]

        return servers

    async def get_server_by_id(
        self,
        server_id: str,
        include_system: bool = True,
    ) -> MCPServer | None:
        """Get an MCP server by ID, including system servers if requested.

        Args:
            server_id: The server ID to look up
            include_system: If True, also search in system workspace for public servers

        Returns:
            The MCPServer if found, None otherwise
        """
        # Build query to find server in user's workspace OR in system workspace (if public)
        query = select(self.model_class).where(self.model_class.id == server_id)

        if include_system:
            query = query.where(
                or_(
                    self.model_class.workspace_id == self.user_context.workspace_id,
                    (self.model_class.workspace_id == "system") & self.model_class.is_public,
                )
            )
        else:
            query = query.where(self.model_class.workspace_id == self.user_context.workspace_id)

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
