"""Project application service."""

import logging
from typing import Any
from uuid import UUID, uuid4

from agentarea_projects.domain.models import Project
from agentarea_projects.infrastructure.repository import ProjectRepository

logger = logging.getLogger(__name__)


class ProjectService:
    """Service for managing projects and their associations."""

    def __init__(self, repository: ProjectRepository):
        self.repository = repository

    async def create(
        self,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        parent_project_id: UUID | str | None = None,
    ) -> Project:
        """Create a new project, auto-generating minio_prefix."""
        project_id = uuid4()
        minio_prefix = f"projects/{project_id}/files/"
        return await self.repository.create(
            id=project_id,
            name=name,
            description=description,
            instructions=instructions,
            parent_project_id=str(parent_project_id) if parent_project_id else None,
            minio_prefix=minio_prefix,
        )

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

    async def update(
        self,
        project_id: UUID | str,
        **kwargs: Any,
    ) -> Project | None:
        """Update a project's fields."""
        return await self.repository.update(project_id, **kwargs)

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

    async def remove_mcp_instance(self, project_id: UUID | str, mcp_instance_id: UUID | str) -> None:
        """Remove an MCP server instance from a project."""
        await self.repository.remove_mcp_instance(project_id, mcp_instance_id)

    # --- Agent associations ---

    async def add_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Add an agent to a project."""
        await self.repository.add_agent(project_id, agent_id)

    async def remove_agent(self, project_id: UUID | str, agent_id: UUID | str) -> None:
        """Remove an agent from a project."""
        await self.repository.remove_agent(project_id, agent_id)
