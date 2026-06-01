from datetime import datetime
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import agent_skills_table


class AgentRepository(WorkspaceScopedRepository[Agent]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Agent, user_context)

    async def get(self, id: UUID | str) -> Agent | None:
        """Get an agent by ID. Delegates to get_by_id for compatibility."""
        return await self.get_by_id(id)

    async def get_agent_by_name(self, name: str) -> Agent | None:
        """Get agent by name."""
        agents = await self.list_all(name=name)
        return agents[0] if agents else None

    async def get_by_slug(self, slug: str) -> Agent | None:
        """Get agent by workspace-scoped slug."""
        query = (
            select(self.model_class)
            .where(self.model_class.slug == slug)
            .where(self._get_workspace_filter())
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

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
            .where(self._get_workspace_filter())
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
