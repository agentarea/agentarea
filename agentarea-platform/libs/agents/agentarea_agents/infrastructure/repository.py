from datetime import datetime
from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import agent_skills_table


class AgentRepository(WorkspaceScopedRepository[Agent]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Agent, user_context)

    def _get_workspace_filter_with_system(self):
        """Get workspace filter that includes both user's workspace and system workspace."""
        return or_(
            self.model_class.workspace_id == self.user_context.workspace_id,
            self.model_class.workspace_id == "system",
        )

    async def list_all(
        self,
        limit: int | None = None,
        offset: int | None = None,
        **filters: Any,
    ) -> list[Agent]:
        """List all agents including system agents.

        Override to include system workspace agents in addition to user's workspace agents.

        Returns all resources within the workspace scope, including system agents.
        Access control should be handled by authorization layer (future ReBAC).
        """
        try:
            query = select(self.model_class)

            # Include both user's workspace AND system workspace
            query = query.where(self._get_workspace_filter_with_system())

            # Apply additional filters
            for field, value in filters.items():
                if hasattr(self.model_class, field):
                    query = query.where(getattr(self.model_class, field) == value)

            # Apply pagination
            if offset is not None:
                query = query.offset(offset)
            if limit is not None:
                query = query.limit(limit)

            result = await self.session.execute(query)
            records = list(result.scalars().all())

            # Log list access
            self.audit_logger.log_list(
                resource_type=self.resource_type,
                user_context=self.user_context,
                count=len(records),
                filters=filters,
                creator_scoped=False,  # No longer used, kept for audit log compatibility
                limit=limit,
                offset=offset,
            )

            return records
        except Exception as e:
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                operation="list_all",
                filters=filters,
            )
            raise

    async def get_by_id(self, id: UUID | str, creator_scoped: bool = False) -> Agent | None:
        """Get an agent by ID, including system agents.

        Override to include system workspace agents in addition to user's workspace agents.
        """
        try:
            query = select(self.model_class).where(self.model_class.id == id)

            if creator_scoped:
                query = query.where(self._get_creator_workspace_filter())
            else:
                # Include both user's workspace AND system workspace
                query = query.where(self._get_workspace_filter_with_system())

            result = await self.session.execute(query)
            record = result.scalar_one_or_none()

            # Log read access
            self.audit_logger.log_read(
                resource_type=self.resource_type,
                user_context=self.user_context,
                resource_id=id,
                creator_scoped=creator_scoped,
                found=record is not None,
            )

            return record
        except Exception as e:
            self.audit_logger.log_error(
                resource_type=self.resource_type,
                user_context=self.user_context,
                error=str(e),
                resource_id=id,
                operation="get_by_id",
            )
            raise

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

    async def get_with_skills(self, agent_id: UUID | str) -> Agent | None:
        """Get an agent with its associated skills loaded.

        Args:
            agent_id: The agent ID.

        Returns:
            The agent with skills relationship loaded, or None if not found.
        """
        query = (
            select(self.model_class)
            .where(self.model_class.id == agent_id)
            .where(self._get_workspace_filter_with_system())
            .options(selectinload(self.model_class.skills))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def set_skills(self, agent_id: UUID, skill_ids: list[UUID]) -> None:
        """Set the skills for an agent, replacing any existing associations.

        Args:
            agent_id: The agent ID.
            skill_ids: List of skill IDs to associate with the agent.
        """
        # Remove existing associations
        await self.session.execute(
            delete(agent_skills_table).where(agent_skills_table.c.agent_id == agent_id)
        )

        # Add new associations
        for skill_id in skill_ids:
            await self.session.execute(
                agent_skills_table.insert().values(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    created_at=datetime.now(),
                )
            )

    async def add_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        """Add a skill to an agent.

        Args:
            agent_id: The agent ID.
            skill_id: The skill ID to add.
        """
        # Check if association already exists
        query = select(agent_skills_table).where(
            and_(
                agent_skills_table.c.agent_id == agent_id,
                agent_skills_table.c.skill_id == skill_id,
            )
        )
        result = await self.session.execute(query)
        existing = result.scalar_one_or_none()

        if existing is None:
            await self.session.execute(
                agent_skills_table.insert().values(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    created_at=datetime.now(),
                )
            )

    async def remove_skill(self, agent_id: UUID, skill_id: UUID) -> None:
        """Remove a skill from an agent.

        Args:
            agent_id: The agent ID.
            skill_id: The skill ID to remove.
        """
        await self.session.execute(
            delete(agent_skills_table).where(
                and_(
                    agent_skills_table.c.agent_id == agent_id,
                    agent_skills_table.c.skill_id == skill_id,
                )
            )
        )
