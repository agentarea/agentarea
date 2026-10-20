"""ProjectsToolset — manage workspace projects and their associations.

Tool method signatures are explicit kwargs (MCP-idiomatic flat wire schema)
but the source of truth for ``create``/``update`` is the Pydantic DTO
``ProjectCreate``/``ProjectUpdate`` in ``agentarea_projects.schemas.dto``.
The contract test in ``tests/unit/test_mcp_rest_parity.py`` enforces parity
between toolset kwargs and DTO fields.
"""

import json
from typing import Annotated
from uuid import UUID

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from agentarea_projects.schemas.dto import ProjectCreate, ProjectUpdate
from pydantic import BaseModel, Field

from .base import platform_context, platform_read_context

PROJECTS_ARE_MEMBER_LEVEL = (
    "every /v1/projects route is member-level; the workspace-scoped repository is the boundary"
)


ProjectId = Annotated[
    str, Field(description="Project id (UUID), from `projects_list` or `projects_create`.")
]


class ProjectSummary(BaseModel):
    id: str = Field(description="Project id (UUID).")
    name: str = Field(description="Project name.")
    description: str | None = Field(default=None, description="Short summary of the project.")


class ProjectDetail(ProjectSummary):
    instructions: str | None = Field(
        default=None, description="Instructions shared across the project's agents."
    )
    parent_project_id: str | None = Field(
        default=None, description="Id of the parent project; null for a top-level project."
    )


class ProjectRef(BaseModel):
    id: str = Field(description="Project id (UUID).")
    name: str = Field(description="Project name.")


class ProjectDeleted(BaseModel):
    deleted: bool = Field(description="True when a project was deleted; false when none matched.")


class ProjectLinkAdded(BaseModel):
    added: bool = Field(description="Always true: the resource is attached to the project.")


class ProjectLinkRemoved(BaseModel):
    removed: bool = Field(description="Always true: the resource is no longer attached.")


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

    open_world = False

    @tool_method(display_name="List projects", effect="read", output=list[ProjectSummary])
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def list(
        self,
        limit: Annotated[int, Field(description="Maximum number of projects to return.")] = 50,
        offset: Annotated[int, Field(description="Number of projects to skip, for paging.")] = 0,
    ) -> str:
        """List projects in the workspace."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            projects = await service.list(limit=limit, offset=offset)
            return json.dumps(
                [{"id": str(p.id), "name": p.name, "description": p.description} for p in projects],
                default=str,
            )

    @tool_method(display_name="Get project", effect="read", output=ProjectDetail)
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def get(self, project_id: ProjectId) -> str:
        """Get a project by ID."""
        async with platform_read_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.get(UUID(project_id))
            if not project:
                raise ToolError("Project not found")
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

    @tool_method(display_name="Create project", effect="write", output=ProjectRef)
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def create(
        self,
        name: Annotated[
            str, Field(description="Project name, 1-255 characters, unique in the workspace.")
        ],
        description: Annotated[
            str | None,
            Field(description="Short summary of the project's purpose, at most 1000 characters."),
        ] = None,
        instructions: Annotated[
            str | None,
            Field(
                description="Instructions shared across the project's agents, at most "
                "20000 characters."
            ),
        ] = None,
        parent_project_id: Annotated[
            str | None,
            Field(
                description="Parent project id (UUID), from `projects_list`, to create a "
                "sub-project; omit for a top-level project."
            ),
        ] = None,
    ) -> str:
        """Create a new project."""
        try:
            parent_id = UUID(parent_project_id) if parent_project_id is not None else None
        except ValueError:
            raise ToolError(
                f"parent_project_id must be a UUID, got {parent_project_id!r}"
            ) from None
        payload = ProjectCreate(
            name=name,
            description=description,
            instructions=instructions,
            parent_project_id=parent_id,
        )
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.create_project(payload)
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method(display_name="Update project", effect="write", idempotent=True, output=ProjectRef)
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def update(
        self,
        project_id: ProjectId,
        name: Annotated[
            str | None, Field(description="New project name, 1-255 characters; omit to keep.")
        ] = None,
        description: Annotated[
            str | None,
            Field(description="New project description, at most 1000 characters; omit to keep."),
        ] = None,
        instructions: Annotated[
            str | None,
            Field(description="New shared instructions, at most 20000 characters; omit to keep."),
        ] = None,
        parent_project_id: Annotated[
            str | None,
            Field(
                description="Id (UUID) of the project to nest this one under, from "
                "`projects_list`; not itself or one of its sub-projects. Omit to keep."
            ),
        ] = None,
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
            try:
                patch["parent_project_id"] = UUID(parent_project_id)
            except ValueError:
                raise ToolError(
                    f"parent_project_id must be a UUID, got {parent_project_id!r}"
                ) from None
        payload = ProjectUpdate.model_validate(patch)

        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            project = await service.update_project(UUID(project_id), payload)
            if not project:
                raise ToolError("Project not found")
            return json.dumps({"id": str(project.id), "name": project.name}, default=str)

    @tool_method(
        display_name="Delete project", effect="destructive", idempotent=True, output=ProjectDeleted
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def delete(self, project_id: ProjectId) -> str:
        """Delete a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            deleted = await service.delete(UUID(project_id))
            return json.dumps({"deleted": deleted})

    @tool_method(
        display_name="Attach skill to project",
        effect="write",
        idempotent=True,
        output=ProjectLinkAdded,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def add_skill(
        self,
        project_id: ProjectId,
        skill_id: Annotated[str, Field(description="Skill id (UUID), from `skills_list`.")],
    ) -> str:
        """Attach a skill to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach skill from project",
        effect="write",
        idempotent=True,
        output=ProjectLinkRemoved,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def remove_skill(
        self,
        project_id: ProjectId,
        skill_id: Annotated[str, Field(description="Skill id (UUID), from `skills_list`.")],
    ) -> str:
        """Detach a skill from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_skill(UUID(project_id), UUID(skill_id))
            return json.dumps({"removed": True})

    @tool_method(
        display_name="Attach agent to project",
        effect="write",
        idempotent=True,
        output=ProjectLinkAdded,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def add_agent(
        self,
        project_id: ProjectId,
        agent_id: Annotated[str, Field(description="Agent id (UUID), from `agents_list`.")],
    ) -> str:
        """Attach an agent to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach agent from project",
        effect="write",
        idempotent=True,
        output=ProjectLinkRemoved,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def remove_agent(
        self,
        project_id: ProjectId,
        agent_id: Annotated[str, Field(description="Agent id (UUID), from `agents_list`.")],
    ) -> str:
        """Detach an agent from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_agent(UUID(project_id), UUID(agent_id))
            return json.dumps({"removed": True})

    @tool_method(
        display_name="Attach MCP instance to project",
        effect="write",
        idempotent=True,
        output=ProjectLinkAdded,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def add_mcp_instance(
        self,
        project_id: ProjectId,
        mcp_instance_id: Annotated[
            str, Field(description="MCP server instance id (UUID), from `mcp_servers_list`.")
        ],
    ) -> str:
        """Attach an MCP server instance to a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.add_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"added": True})

    @tool_method(
        display_name="Detach MCP instance from project",
        effect="write",
        idempotent=True,
        output=ProjectLinkRemoved,
    )
    @unrestricted(PROJECTS_ARE_MEMBER_LEVEL)
    async def remove_mcp_instance(
        self,
        project_id: ProjectId,
        mcp_instance_id: Annotated[
            str,
            Field(description="MCP server instance id (UUID), from `mcp_servers_list`."),
        ],
    ) -> str:
        """Detach an MCP server instance from a project."""
        async with platform_context() as (_session, _user_ctx, repo_factory, _broker, _secret):
            service = _build_service(repo_factory)
            await service.remove_mcp_instance(UUID(project_id), UUID(mcp_instance_id))
            return json.dumps({"removed": True})
