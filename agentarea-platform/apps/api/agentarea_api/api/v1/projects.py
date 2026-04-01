"""Projects CRUD API endpoints."""

import logging
from typing import Annotated, Any
from uuid import UUID

from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from fastapi import APIRouter, Depends, HTTPException, UploadFile
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


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    instructions: str | None = None
    parent_project_id: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None


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
    key: str
    size: int
    last_modified: str


class ProjectFileListResponse(BaseModel):
    files: list[ProjectFileInfo]
    prefix: str


class ProjectFileDownloadResponse(BaseModel):
    url: str
    key: str


class ProjectResponse(BaseModel):
    id: UUID
    workspace_id: str
    created_by: str
    name: str
    description: str | None
    instructions: str | None
    parent_project_id: str | None
    minio_prefix: str
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
    project = await service.create(
        name=data.name,
        description=data.description,
        instructions=data.instructions,
        parent_project_id=data.parent_project_id,
    )
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
    update_data = data.model_dump(exclude_none=True)
    project = await service.update(project_id, **update_data)
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
# File endpoints (MinIO / S3)
# ---------------------------------------------------------------------------


def _get_s3_client():
    from agentarea_common.config.aws import get_s3_client

    return get_s3_client()


def _get_bucket() -> str:
    from agentarea_common.config.aws import get_aws_settings

    return get_aws_settings().S3_BUCKET_NAME


@router.post("/{project_id}/files", status_code=204)
async def upload_project_file(
    project_id: UUID,
    file: UploadFile,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Upload a file to a project's MinIO prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    client = _get_s3_client()
    bucket = _get_bucket()
    key = f"{project.minio_prefix}{file.filename}"

    content = await file.read()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=file.content_type or "application/octet-stream",
    )


@router.get("/{project_id}/files", response_model=ProjectFileListResponse)
async def list_project_files(
    project_id: UUID,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """List all files in a project's MinIO prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    client = _get_s3_client()
    bucket = _get_bucket()

    paginator = client.get_paginator("list_objects_v2")
    files = []
    for page in paginator.paginate(Bucket=bucket, Prefix=project.minio_prefix):
        for obj in page.get("Contents", []):
            relative_path = obj["Key"][len(project.minio_prefix) :]
            files.append(
                {
                    "path": relative_path,
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
            )
    return {"files": files, "prefix": project.minio_prefix}


@router.get("/{project_id}/files/{file_path:path}", response_model=ProjectFileDownloadResponse)
async def download_project_file(
    project_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Download a file from a project's MinIO prefix (presigned URL)."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    client = _get_s3_client()
    bucket = _get_bucket()
    key = f"{project.minio_prefix}{file_path}"

    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=3600,
        )
        return {"url": url, "key": key}
    except Exception as e:
        logger.error("Failed to generate presigned URL for %s: %s", key, e)
        raise HTTPException(status_code=404, detail="File not found") from e


@router.delete("/{project_id}/files/{file_path:path}", status_code=204)
async def delete_project_file(
    project_id: UUID,
    file_path: str,
    user_context: UserContextDep,
    service: ProjectServiceDep,
):
    """Delete a file from a project's MinIO prefix."""
    project = await service.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    client = _get_s3_client()
    bucket = _get_bucket()
    key = f"{project.minio_prefix}{file_path}"

    client.delete_object(Bucket=bucket, Key=key)
