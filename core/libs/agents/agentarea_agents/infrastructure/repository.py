from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_agents.domain.models import Agent


class AgentRepository(WorkspaceScopedRepository[Agent]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Agent, user_context)

    async def get(self, id: UUID | str) -> Agent | None:
        """Get an agent by ID. Delegates to get_by_id for compatibility."""
        return await self.get_by_id(id)

    async def get_by_workspace_id(
        self, workspace_id: str, limit: int = 100, offset: int = 0
    ) -> list[Agent]:
        """Get agents by workspace ID with pagination.

        Note: This method is deprecated. Use list_all() instead which automatically
        filters by the current workspace from user context.
        """
        # For backward compatibility, but this should be replaced with list_all()
        if workspace_id != self.user_context.workspace_id:
            return []  # Don't allow cross-workspace access

        return await self.list_all(limit=limit, offset=offset)

    async def create_from_entity(self, agent: Agent) -> Agent:
        """Create a new agent from domain entity.

        Note: This method is deprecated. Use create() with field parameters instead.
        """
        # Extract fields from the agent entity
        agent_data = {
            "id": agent.id,
            "name": agent.name,
            "status": agent.status,
            "description": getattr(agent, "description", None),
            "config": getattr(agent, "config", None),
            "created_at": agent.created_at,
            "updated_at": agent.updated_at,
        }

        # Remove None values and system fields that will be auto-populated
        agent_data = {k: v for k, v in agent_data.items() if v is not None}
        agent_data.pop("created_at", None)
        agent_data.pop("updated_at", None)

        return await self.create(**agent_data)

    async def update_entity(self, agent: Agent) -> Agent:
        """Update an existing agent from domain entity.

        Note: This method is deprecated. Use update() with field parameters instead.
        """
        # Extract fields from the agent entity
        agent_data = {
            "name": agent.name,
            "status": agent.status,
            "description": getattr(agent, "description", None),
            "config": getattr(agent, "config", None),
        }

        # Remove None values
        agent_data = {k: v for k, v in agent_data.items() if v is not None}

        updated_agent = await self.update(str(agent.id), creator_scoped=False, **agent_data)
        return updated_agent or agent
