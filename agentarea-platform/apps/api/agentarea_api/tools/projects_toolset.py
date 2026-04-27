"""ProjectsToolset — manage workspace projects and their associations."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context, platform_read_context


class ProjectsToolset(Toolset):
    """Manage projects: list, get, create, update, delete, and attach skills/agents/MCP instances."""

    @tool_method
    async def list(self, limit: int = 50, offset: int = 0) -> str:
        """List projects in the workspace."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            projects = await service.list(limit=limit, offset=offset)
            return json.dumps(
                [
                    {"id": str(p.id), "name": p.name, "description": p.description}
                    for p in projects
                ],
                default=str,
            )

    @tool_method
    async def get(self, project_id: str) -> str:
        """Get a project by ID."""
        from uuid import UUID

        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
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

    @tool_method
    async def create(
        self,
        name: str,
        description: str = "",
        instructions: str = "",
        parent_project_id: str = "",
    ) -> str:
        """Create a new project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            project = await service.create(
                name=name,
                description=description or None,
                instructions=instructions or None,
                parent_project_id=parent_project_id or None,
            )
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method
    async def update(
        self,
        project_id: str,
        name: str = "",
        description: str = "",
        instructions: str = "",
    ) -> str:
        """Update a project's fields."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            kwargs = {}
            if name:
                kwargs["name"] = name
            if description:
                kwargs["description"] = description
            if instructions:
                kwargs["instructions"] = instructions
            project = await service.update(UUID(project_id), **kwargs)
            if not project:
                return json.dumps({"error": "Project not found"})
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method
    async def delete(self, project_id: str) -> str:
        """Delete a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            deleted = await service.delete(UUID(project_id))
            return json.dumps({"deleted": deleted})

    @tool_method
    async def add_skill(self, project_id: str, skill_id: str) -> str:
        """Attach a skill to a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.add_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"added": True})

    @tool_method
    async def remove_skill(self, project_id: str, skill_id: str) -> str:
        """Detach a skill from a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.remove_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"removed": True})

    @tool_method
    async def add_agent(self, project_id: str, agent_id: str) -> str:
        """Attach an agent to a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.add_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"added": True})

    @tool_method
    async def remove_agent(self, project_id: str, agent_id: str) -> str:
        """Detach an agent from a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.remove_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"removed": True})

    @tool_method
    async def add_mcp_instance(self, project_id: str, mcp_instance_id: str) -> str:
        """Attach an MCP server instance to a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.add_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"added": True})

    @tool_method
    async def remove_mcp_instance(self, project_id: str, mcp_instance_id: str) -> str:
        """Detach an MCP server instance from a project."""
        from uuid import UUID

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            from agentarea_projects.application.service import ProjectService
            from agentarea_projects.infrastructure.repository import ProjectRepository

            service = ProjectService(repo_factory.create_repository(ProjectRepository))
            await service.remove_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"removed": True})
