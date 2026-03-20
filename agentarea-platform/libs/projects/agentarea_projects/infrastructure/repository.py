"""Project repository."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agentarea_projects.domain.models import (
    Project,
    project_agents,
    project_mcp_instances,
    project_skills,
)


class ProjectRepository(WorkspaceScopedRepository[Project]):
    """Repository for Project entities with junction table helpers."""

    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, Project, user_context)

    async def get_by_id(self, id: UUID | str, creator_scoped: bool = False) -> Project | None:  # type: ignore[override]
        """Get project by ID with eager-loaded associations."""
        query = (
            select(Project)
            .where(Project.id == id)
            .where(self._get_workspace_filter())
            .options(
                selectinload(Project.skills),
                selectinload(Project.mcp_instances),
                selectinload(Project.agents),
            )
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def list_all(self, limit: int | None = None, offset: int | None = None, **filters) -> list[Project]:  # type: ignore[override]
        """List all projects in the workspace with associations."""
        query = (
            select(Project)
            .where(self._get_workspace_filter())
            .options(
                selectinload(Project.skills),
                selectinload(Project.mcp_instances),
                selectinload(Project.agents),
            )
        )
        for field, value in filters.items():
            if hasattr(Project, field):
                query = query.where(getattr(Project, field) == value)
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # --- Skill junction helpers ---

    async def add_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Add a skill to a project."""
        stmt = insert(project_skills).values(
            project_id=str(project_id), skill_id=str(skill_id)
        ).on_conflict_do_nothing()
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Remove a skill from a project."""
        stmt = delete(project_skills).where(
            project_skills.c.project_id == str(project_id),
            project_skills.c.skill_id == str(skill_id),
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # --- MCP instance junction helpers ---

    async def add_mcp_instance(self, project_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        """Add an MCP server instance to a project."""
        stmt = insert(project_mcp_instances).values(
            project_id=str(project_id), mcp_instance_id=str(mcp_instance_id)
        ).on_conflict_do_nothing()
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_mcp_instance(self, project_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        """Remove an MCP server instance from a project."""
        stmt = delete(project_mcp_instances).where(
            project_mcp_instances.c.project_id == str(project_id),
            project_mcp_instances.c.mcp_instance_id == str(mcp_instance_id),
        )
        await self.session.execute(stmt)
        await self.session.commit()

    # --- Agent junction helpers ---

    async def add_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Add an agent to a project."""
        stmt = insert(project_agents).values(
            project_id=str(project_id), agent_id=str(agent_id)
        ).on_conflict_do_nothing()
        await self.session.execute(stmt)
        await self.session.commit()

    async def remove_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Remove an agent from a project."""
        stmt = delete(project_agents).where(
            project_agents.c.project_id == str(project_id),
            project_agents.c.agent_id == str(agent_id),
        )
        await self.session.execute(stmt)
        await self.session.commit()
