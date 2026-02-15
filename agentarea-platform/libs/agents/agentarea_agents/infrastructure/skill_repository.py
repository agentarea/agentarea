"""Skill repository for database operations."""

from typing import Any
from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.skill_models import AgentSkill, Skill


class SkillRepository(WorkspaceScopedRepository[Skill]):
    """Repository for Skill CRUD operations."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Skill, user_context)

    async def get_by_name(self, name: str) -> Skill | None:
        """Get a skill by name within the current workspace.

        Args:
            name: The skill name to search for.

        Returns:
            The skill if found, None otherwise.
        """
        query = select(self.model_class).where(
            self.model_class.workspace_id == self.user_context.workspace_id,
            self.model_class.name == name,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_with_agents(self, skill_id: UUID | str) -> Skill | None:
        """Get a skill with its associated agents loaded.

        Args:
            skill_id: The skill ID.

        Returns:
            The skill with agents relationship loaded.
        """
        query = (
            select(self.model_class)
            .where(
                self.model_class.id == skill_id,
                self.model_class.workspace_id == self.user_context.workspace_id,
            )
            .options(selectinload(self.model_class.agents))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_by_source_type(self, source_type: str) -> list[Skill]:
        """List all skills of a specific source type.

        Args:
            source_type: The source type to filter by (content, zip, github, path).

        Returns:
            List of skills with the specified source type.
        """
        return await self.list_all(source_type=source_type)

    async def add_agent_association(self, skill_id: UUID, agent_id: UUID) -> None:
        """Add an agent-skill association.

        Args:
            skill_id: The skill ID.
            agent_id: The agent ID.
        """
        # Check if association already exists
        query = select(AgentSkill).where(
            AgentSkill.skill_id == skill_id,
            AgentSkill.agent_id == agent_id,
        )
        result = await self.session.execute(query)
        existing = result.scalar_one_or_none()

        if existing is None:
            association = AgentSkill(skill_id=skill_id, agent_id=agent_id)
            self.session.add(association)

    async def remove_agent_association(self, skill_id: UUID, agent_id: UUID) -> None:
        """Remove an agent-skill association.

        Args:
            skill_id: The skill ID.
            agent_id: The agent ID.
        """
        query = select(AgentSkill).where(
            AgentSkill.skill_id == skill_id,
            AgentSkill.agent_id == agent_id,
        )
        result = await self.session.execute(query)
        association = result.scalar_one_or_none()

        if association:
            await self.session.delete(association)

    async def get_skills_for_agent(self, agent_id: UUID) -> list[Skill]:
        """Get all skills associated with an agent.

        Args:
            agent_id: The agent ID.

        Returns:
            List of skills associated with the agent.
        """
        query = (
            select(Skill)
            .join(AgentSkill, AgentSkill.skill_id == Skill.id)
            .where(
                AgentSkill.agent_id == agent_id,
                Skill.workspace_id == self.user_context.workspace_id,
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
