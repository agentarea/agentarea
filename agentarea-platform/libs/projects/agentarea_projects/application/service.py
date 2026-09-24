"""Project application service."""

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_agents.infrastructure.skill_repository import SkillRepository
from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.exceptions.errors import NotFoundError
from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_projects.domain.models import Project
from agentarea_projects.infrastructure.repository import ProjectRepository
from agentarea_projects.schemas.dto import ProjectCreate, ProjectUpdate

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing projects and their associations."""

    def __init__(self, repository: ProjectRepository):
        self.repository = repository

    async def create_project(self, payload: ProjectCreate) -> Project:
        """Create a new project.

        Files are stored under ``projects/{id}/`` in ``ArtifactService``
        (workspace-scoped); the prefix is fully derived from the project id
        and is not persisted on the row.
        """
        return await self.repository.create(
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
            parent_project_id=(
                str(payload.parent_project_id) if payload.parent_project_id else None
            ),
        )

    async def update_project(
        self,
        project_id: UUID | str,
        payload: ProjectUpdate,
    ) -> Project | None:
        """Apply a partial update to a project. Only fields explicitly set on
        the payload are written — unset fields remain unchanged.
        """
        patch = payload.model_dump(exclude_unset=True)
        if "parent_project_id" in patch and patch["parent_project_id"] is not None:
            patch["parent_project_id"] = str(patch["parent_project_id"])
        if await self.repository.update(project_id, **patch) is None:
            return None
        return await self.repository.get_by_id(project_id)

    async def get(self, project_id: UUID | str) -> Project | None:
        """Get a project by ID."""
        return await self.repository.get_by_id(project_id)

    async def list(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[Project]:
        """List all projects in the current workspace."""
        return await self.repository.list_all(limit=limit, offset=offset)

    async def delete(self, project_id: UUID | str) -> bool:
        """Delete a project."""
        return await self.repository.delete(project_id)

    # --- Associations ---
    # Link rows carry no workspace of their own: both ends are resolved in the
    # caller's workspace first, and a miss is a 404 whether the id is foreign
    # or unknown.

    async def _in_workspace(
        self,
        repository_class: Callable[[AsyncSession, UserContext], WorkspaceScopedRepository[Any]],
        record_id: UUID | str,
        label: str,
    ) -> UUID:
        try:
            record_uuid = UUID(str(record_id))
        except ValueError:
            raise NotFoundError(f"{label} not found") from None
        repository = repository_class(self.repository.session, self.repository.user_context)
        if await repository.get_by_id(record_uuid) is None:
            raise NotFoundError(f"{label} not found")
        return record_uuid

    async def _project_id(self, project_id: UUID | str) -> UUID:
        return await self._in_workspace(ProjectRepository, project_id, "Project")

    async def add_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Add a skill to a project."""
        await self.repository.add_skill(
            await self._project_id(project_id),
            await self._in_workspace(SkillRepository, skill_id, "Skill"),
        )

    async def remove_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Remove a skill from a project."""
        await self.repository.remove_skill(await self._project_id(project_id), skill_id)

    async def add_mcp_instance(self, project_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        """Add an MCP server instance to a project."""
        await self.repository.add_mcp_instance(
            await self._project_id(project_id),
            await self._in_workspace(MCPServerInstanceRepository, mcp_instance_id, "MCP instance"),
        )

    async def remove_mcp_instance(
        self, project_id: UUID | str, mcp_instance_id: UUID | str
    ) -> None:
        """Remove an MCP server instance from a project."""
        await self.repository.remove_mcp_instance(
            await self._project_id(project_id), mcp_instance_id
        )

    async def add_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Add an agent to a project."""
        await self.repository.add_agent(
            await self._project_id(project_id),
            await self._in_workspace(AgentRepository, agent_id, "Agent"),
        )

    async def remove_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Remove an agent from a project."""
        await self.repository.remove_agent(await self._project_id(project_id), agent_id)
