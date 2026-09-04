"""ProjectsToolset — manage workspace projects and their associations.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create``/``update`` is the Pydantic DTO
``ProjectCreate``/``ProjectUpdate`` in ``agentarea_projects.schemas.dto``.
The contract test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity
between toolset kwargs and DTO fields.
"""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from agentarea_projects.schemas.dto import ProjectCreate, ProjectUpdate

from .base import platform_context, platform_read_context


def _build_service(repo_factory) -> ProjectService:
    return ProjectService(repo_factory.create_repository(ProjectRepository))


@toolset(
    namespace="agentarea/projects",
    display_name="Projects",
    description="Manage projects and their skills/agents/MCP instances.",
    category="platform",
    plane="build",
)
class ProjectsToolset(Toolset):
    """Manage projects: list, get, create, update, delete, and attach skills/agents/MCP instances."""

    @tool_method(effect="read")
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List projects in the workspace."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            projects = await service.list(limit=limit, offset=offset)
            return json.dumps(
                [{"id": str(p.id), "name": p.name, "description": p.description} for p in projects],
                default=str,
            )

    @tool_method(effect="read")
    async def get(self, project_id: str) -> str:
        """Get a project by ID."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.get(UUID(project_id))
            if not project:
                return json.dumps({"error": "Project not found"})
            return json.dumps(
                {
                    "id": str(project.id),
                    "name": project.name,
                    "description": project.description,
                    "instructions": project.instructions,
                    "parent_project_id": (
                        str(project.parent_project_id) if project.parent_project_id else None
                    ),
                },
                default=str,
            )

    @tool_method(effect="write")
    async def create(
        self,
        name: str,
        description: str | None = None,
        instructions: str | None = None,
        parent_project_id: str | None = None,
    ) -> str:
        """Create a new project."""
        payload = ProjectCreate(
            name=name,
            description=description,
            instructions=instructions,
            parent_project_id=parent_project_id,
        )
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.create_project(payload)
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method(effect="write")
    async def update(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        parent_project_id: str | None = None,
    ) -> str:
        """Update a project's fields. Only fields explicitly set are written."""
        patch: dict[str, object] = {}
        if name is not None:
            patch["name"] = name
        if description is not None:
            patch["description"] = description
        if instructions is not None:
            patch["instructions"] = instructions
        if parent_project_id is not None:
            patch["parent_project_id"] = parent_project_id
        payload = ProjectUpdate.model_validate(patch)

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.update_project(UUID(project_id), payload)
            if not project:
                return json.dumps({"error": "Project not found"})
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method(effect="destructive")
    async def delete(self, project_id: str) -> str:
        """Delete a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete(UUID(project_id))
            return json.dumps({"deleted": deleted})

    @tool_method(effect="write")
    async def add_skill(self, project_id: str, skill_id: str) -> str:
        """Attach a skill to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"added": True})

    @tool_method(effect="write")
    async def remove_skill(self, project_id: str, skill_id: str) -> str:
        """Detach a skill from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"removed": True})

    @tool_method(effect="write")
    async def add_agent(self, project_id: str, agent_id: str) -> str:
        """Attach an agent to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"added": True})

    @tool_method(effect="write")
    async def remove_agent(self, project_id: str, agent_id: str) -> str:
        """Detach an agent from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"removed": True})

    @tool_method(effect="write")
    async def add_mcp_instance(self, project_id: str, mcp_instance_id: str) -> str:
        """Attach an MCP server instance to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"added": True})

    @tool_method(effect="write")
    async def remove_mcp_instance(self, project_id: str, mcp_instance_id: str) -> str:
        """Detach an MCP server instance from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"removed": True})
