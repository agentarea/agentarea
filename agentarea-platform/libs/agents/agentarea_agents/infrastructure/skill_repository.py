"""Skill repository for database operations."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_agents.domain.skill_models import (
    Skill,
    SkillMember,
    agent_skills_table,
    skill_members_table,
)


class SkillRepository(WorkspaceScopedRepository[Skill]):
    """Repository for Skill CRUD operations."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Skill, user_context)

    async def get_by_name(self, name: str) -> Skill | None:
        """Get a skill by name within accessible workspaces.

        Args:
            name: The skill name to search for.

        Returns:
            The skill if found, None otherwise.
        """
        query = select(self.model_class).where(
            self.model_class.name == name,
            self._get_workspace_filter(),
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Skill | None:
        """Get a skill by workspace-scoped slug.

        Args:
            slug: The slug to search for.

        Returns:
            The skill if found, None otherwise.
        """
        query = select(self.model_class).where(
            self.model_class.slug == slug,
            self._get_workspace_filter(),
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
                self._get_workspace_filter(),
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
                self._get_workspace_filter(),
            )
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Skill member management (self-referential skill-as-bundle)
    # ------------------------------------------------------------------

    async def get_members(self, parent_skill_id: UUID) -> list[SkillMember]:
        """Get all child skills for a parent skill, ordered by 'order' field."""
        query = (
            select(skill_members_table)
            .where(skill_members_table.c.parent_skill_id == parent_skill_id)
            .order_by(skill_members_table.c.order)
        )
        result = await self.session.execute(query)
        rows = result.fetchall()
        return [
            SkillMember(
                parent_skill_id=row.parent_skill_id,
                child_skill_id=row.child_skill_id,
                order=row.order,
                is_required=row.is_required,
                dependencies=row.dependencies or [],
            )
            for row in rows
        ]

    async def add_member(
        self,
        parent_skill_id: UUID,
        child_skill_id: UUID,
        order: int = 0,
        is_required: bool = True,
        dependencies: list[str] | None = None,
    ) -> SkillMember:
        """Add a child skill to a parent skill. Updates if association already exists."""
        query = select(skill_members_table).where(
            and_(
                skill_members_table.c.parent_skill_id == parent_skill_id,
                skill_members_table.c.child_skill_id == child_skill_id,
            )
        )
        result = await self.session.execute(query)
        existing = result.fetchone()

        deps = dependencies or []
        if existing is not None:
            await self.session.execute(
                skill_members_table.update()
                .where(
                    and_(
                        skill_members_table.c.parent_skill_id == parent_skill_id,
                        skill_members_table.c.child_skill_id == child_skill_id,
                    )
                )
                .values(order=order, is_required=is_required, dependencies=deps)
            )
        else:
            await self.session.execute(
                skill_members_table.insert().values(
                    parent_skill_id=parent_skill_id,
                    child_skill_id=child_skill_id,
                    order=order,
                    is_required=is_required,
                    dependencies=deps,
                )
            )
        return SkillMember(
            parent_skill_id=parent_skill_id,
            child_skill_id=child_skill_id,
            order=order,
            is_required=is_required,
            dependencies=deps,
        )

    async def remove_member(self, parent_skill_id: UUID, child_skill_id: UUID) -> bool:
        """Remove a child skill from a parent skill. Returns True if removed."""
        query = select(skill_members_table).where(
            and_(
                skill_members_table.c.parent_skill_id == parent_skill_id,
                skill_members_table.c.child_skill_id == child_skill_id,
            )
        )
        result = await self.session.execute(query)
        if result.fetchone() is None:
            return False
        await self.session.execute(
            skill_members_table.delete().where(
                and_(
                    skill_members_table.c.parent_skill_id == parent_skill_id,
                    skill_members_table.c.child_skill_id == child_skill_id,
                )
            )
        )
        return True
