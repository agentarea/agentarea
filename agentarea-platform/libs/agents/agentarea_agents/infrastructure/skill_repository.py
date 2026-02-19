"""Skill repository for database operations."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.skill_models import Skill, agent_skills_table


class SkillRepository(WorkspaceScopedRepository[Skill]):
    """Repository for Skill CRUD operations."""

    # System workspace ID for global/system skills
    SYSTEM_WORKSPACE_ID = "system"

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Skill, user_context)

    async def get_by_id(self, skill_id: UUID | str, creator_scoped: bool = False) -> Skill | None:
        """Get a skill by ID within the current workspace or system skills.

        Args:
            skill_id: The skill ID
            creator_scoped: If True, also filter by created_by (ignored for system skills)

        Returns:
            The skill if found, None otherwise
        """
        query = select(self.model_class).where(self.model_class.id == skill_id)

        if creator_scoped:
            query = query.where(self._get_creator_workspace_filter())
        else:
            # Include both workspace-specific skills and system skills
            query = query.where(
                or_(
                    self.model_class.workspace_id == self.user_context.workspace_id,
                    self.model_class.workspace_id == self.SYSTEM_WORKSPACE_ID,
                )
            )

        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> Skill | None:
        """Get a skill by name within the current workspace or system skills.

        Args:
            name: The skill name to search for.

        Returns:
            The skill if found, None otherwise.
        """
        query = select(self.model_class).where(
            self.model_class.name == name,
            or_(
                self.model_class.workspace_id == self.user_context.workspace_id,
                self.model_class.workspace_id == self.SYSTEM_WORKSPACE_ID,
            ),
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
                or_(
                    self.model_class.workspace_id == self.user_context.workspace_id,
                    self.model_class.workspace_id == self.SYSTEM_WORKSPACE_ID,
                ),
            )
            .options(selectinload(self.model_class.agents))
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_all(
        self, limit: int | None = None, offset: int | None = None, **filters
    ) -> list[Skill]:
        """List all skills in the workspace, including system skills.

        System skills (workspace_id='system') are visible to all workspaces.

        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            **filters: Additional field filters

        Returns:
            List of skills within workspace scope plus system skills
        """
        query = select(self.model_class)

        # Include both workspace-specific skills and system skills
        query = query.where(
            or_(
                self.model_class.workspace_id == self.user_context.workspace_id,
                self.model_class.workspace_id == self.SYSTEM_WORKSPACE_ID,
            )
        )

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
        return list(result.scalars().all())

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
        query = select(agent_skills_table).where(
            and_(
                agent_skills_table.c.skill_id == skill_id,
                agent_skills_table.c.agent_id == agent_id,
            )
        )
        result = await self.session.execute(query)
        existing = result.scalar_one_or_none()

        if existing is None:
            from datetime import datetime

            await self.session.execute(
                agent_skills_table.insert().values(
                    agent_id=agent_id,
                    skill_id=skill_id,
                    created_at=datetime.now(),
                )
            )

    async def remove_agent_association(self, skill_id: UUID, agent_id: UUID) -> None:
        """Remove an agent-skill association.

        Args:
            skill_id: The skill ID.
            agent_id: The agent ID.
        """
        await self.session.execute(
            agent_skills_table.delete().where(
                and_(
                    agent_skills_table.c.skill_id == skill_id,
                    agent_skills_table.c.agent_id == agent_id,
                )
            )
        )

    async def get_skills_for_agent(self, agent_id: UUID) -> list[Skill]:
        """Get all skills associated with an agent.

        Args:
            agent_id: The agent ID.

        Returns:
            List of skills associated with the agent.
        """
        query = (
            select(Skill)
            .join(agent_skills_table, agent_skills_table.c.skill_id == Skill.id)
            .where(
                agent_skills_table.c.agent_id == agent_id,
                or_(
                    Skill.workspace_id == self.user_context.workspace_id,
                    Skill.workspace_id == self.SYSTEM_WORKSPACE_ID,
                ),
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
