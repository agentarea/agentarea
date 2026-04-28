"""Project application service."""

import logging
from uuid import UUID

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
        return await self.repository.update(project_id, **patch)

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

    # --- Skill associations ---

    async def add_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Add a skill to a project."""
        await self.repository.add_skill(project_id, skill_id)

    async def remove_skill(self, project_id: UUID | str, skill_id: UUID | str) -> None:
        """Remove a skill from a project."""
        await self.repository.remove_skill(project_id, skill_id)

    # --- MCP instance associations ---

    async def add_mcp_instance(self, project_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        """Add an MCP server instance to a project."""
        await self.repository.add_mcp_instance(project_id, mcp_instance_id)

    async def remove_mcp_instance(
        self, project_id: UUID | str, mcp_instance_id: UUID | str
    ) -> None:
        """Remove an MCP server instance from a project."""
        await self.repository.remove_mcp_instance(project_id, mcp_instance_id)

    # --- Agent associations ---

    async def add_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Add an agent to a project."""
        await self.repository.add_agent(project_id, agent_id)

    async def remove_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Remove an agent from a project."""
        await self.repository.remove_agent(project_id, agent_id)
