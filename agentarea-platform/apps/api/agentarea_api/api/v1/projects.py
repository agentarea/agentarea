"""Projects CRUD API endpoints."""

import logging
from pathlib import PurePosixPath
from typing import Annotated, Any
from urllib.parse import quote
from uuid import UUID

from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config.app import get_app_settings
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from agentarea_projects.schemas.dto import ProjectCreate, ProjectUpdate
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------


async def get_project_service(
    repository_factory: RepositoryFactoryDep,
) -> ProjectService:
    """Get a ProjectService instance for the current request."""
    repo = repository_factory.create_repository(ProjectRepository)
    return ProjectService(repo)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AssociationBody(BaseModel):
    id: str


class ProjectSkillRef(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ProjectAgentRef(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ProjectMcpInstanceRef(BaseModel):
    id: UUID
    name: str

    model_config = {"from_attributes": True}


class ProjectFileInfo(BaseModel):
    path: str
    size: int
    last_modified: str | None = None


class ProjectFileListResponse(BaseModel):
    files: list[ProjectFileInfo]


class ProjectFileDownloadResponse(BaseModel):
    url: str
    path: str


class ProjectResponse(BaseModel):
    id: UUID
    workspace_id: str
    created_by: str
    name: str
    description: str | None
    instructions: str | None
    parent_project_id: str | None
    skills: list[ProjectSkillRef] = []
    mcp_instances: list[ProjectMcpInstanceRef] = []
    agents: list[ProjectAgentRef] = []

    model_config = {"from_attributes": True}

    @field_validator("skills", "mcp_instances", "agents", mode="before")
    @classmethod
    def _none_to_empty(cls, v: Any) -> Any:
        return v if v is not None else []


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=ProjectResponse, status_code=201)
async def create_project(
    data: ProjectCreate,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Create a new project."""
    project = await service.create_project(data)
    return ProjectResponse.model_validate(project)


@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    user_context: UserContextDep,
    service: ProjectServiceDep,
    limit: int = 100,
    offset: int = 0,
):
    """List all projects in the current workspace."""
    projects = await service.list(limit=limit, offset=offset)
    return [ProjectResponse.model_validate(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Get a specific project by ID."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Update a project's fields."""
    project = await service.update_project(project_id, data)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Delete a project."""
    deleted = await service.delete(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


# ---------------------------------------------------------------------------
# Association endpoints
# ---------------------------------------------------------------------------


@router.post("/{project_id}/skills", status_code=204)
async def add_skill_to_project(
    project_id: UUID,
    body: AssociationBody,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Add a skill to a project."""
    await service.add_skill(project_id, body.id)


@router.delete("/{project_id}/skills/{skill_id}", status_code=204)
async def remove_skill_from_project(
    project_id: UUID,
    skill_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Remove a skill from a project."""
    await service.remove_skill(project_id, skill_id)


@router.post("/{project_id}/mcp-instances", status_code=204)
async def add_mcp_instance_to_project(
    project_id: UUID,
    body: AssociationBody,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Add an MCP server instance to a project."""
    await service.add_mcp_instance(project_id, body.id)


@router.delete("/{project_id}/mcp-instances/{mcp_instance_id}", status_code=204)
async def remove_mcp_instance_from_project(
    project_id: UUID,
    mcp_instance_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Remove an MCP server instance from a project."""
    await service.remove_mcp_instance(project_id, mcp_instance_id)


@router.post("/{project_id}/agents", status_code=204)
async def add_agent_to_project(
    project_id: UUID,
    body: AssociationBody,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Add an agent to a project."""
    await service.add_agent(project_id, body.id)


@router.delete("/{project_id}/agents/{agent_id}", status_code=204)
async def remove_agent_from_project(
    project_id: UUID,
    agent_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Remove an agent from a project."""
    await service.remove_agent(project_id, agent_id)


# ---------------------------------------------------------------------------
# File endpoints — backed by ArtifactService under
# ``workspaces/{workspace_id}/projects/{project_id}/...``
# ---------------------------------------------------------------------------


def _project_path(project_id: UUID, rel: str = "") -> str:
    rel = rel.lstrip("/")
    return f"projects/{project_id}/{rel}" if rel else f"projects/{project_id}/"


def _project_file_download_url(project_id: UUID, file_path: str) -> str:
    base = get_app_settings().API_BASE_URL.rstrip("/")
    encoded_path = quote(file_path.lstrip("/"), safe="/")
    return f"{base}/v1/projects/{project_id}/files/download/{encoded_path}"


@router.post("/{project_id}/files", status_code=204)
async def upload_project_file(
    project_id: UUID,
    file: UploadFile,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Upload a file to a project's workspace-scoped artifact prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    svc = ArtifactService()
    content = await file.read()
    await svc.put(
        user_context.workspace_id,
        _project_path(project_id, file.filename or "unnamed"),
        content,
        content_type=file.content_type,
    )


@router.get("/{project_id}/files", response_model=ProjectFileListResponse)
async def list_project_files(
    project_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """List files under the project's prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    svc = ArtifactService()
    project_prefix = _project_path(project_id)
    objects = await svc.list(user_context.workspace_id, prefix=project_prefix)
    files = [
        ProjectFileInfo(
            path=obj.path[len(project_prefix) :],
            size=obj.size,
            last_modified=obj.last_modified,
        )
        for obj in objects
    ]
    return ProjectFileListResponse(files=files)


@router.get("/{project_id}/files/download/{file_path:path}")
async def stream_project_file(
    project_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Stream a project file through the AgentArea API."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    svc = ArtifactService()
    full_path = _project_path(project_id, file_path)
    try:
        data, content_type = await svc.get(user_context.workspace_id, full_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None

    filename = PurePosixPath(file_path).name or "file.bin"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)


@router.get("/{project_id}/files/{file_path:path}", response_model=ProjectFileDownloadResponse)
async def download_project_file(
    project_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Return an AgentArea API URL for a project file."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    svc = ArtifactService()
    full_path = _project_path(project_id, file_path)
    if not await svc.exists(user_context.workspace_id, full_path):
        raise HTTPException(status_code=404, detail="File not found")
    url = _project_file_download_url(project_id, file_path)
    return ProjectFileDownloadResponse(url=url, path=file_path)


@router.delete("/{project_id}/files/{file_path:path}", status_code=204)
async def delete_project_file(
    project_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Delete a file from the project's prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    svc = ArtifactService()
    await svc.delete(user_context.workspace_id, _project_path(project_id, file_path))
