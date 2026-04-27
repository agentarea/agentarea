"""Workspace-scoped files API.

Lists and serves the files stored under the current workspace's S3 prefix.
Files end up here from any source — agent tool runs, task artifacts, manual
uploads from a project — so this is a read-only window into whatever the
workspace already owns. Workspace isolation is enforced by ``ArtifactService``,
which prepends ``workspaces/{workspace_id}/`` to every key from
``UserContextDep``.
"""

from __future__ import annotations

import logging
from typing import Annotated

from agentarea_common.artifacts import ArtifactService
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["files"])


class WorkspaceFileInfo(BaseModel):
    path: str
    size: int
    content_type: str | None = None
    last_modified: str | None = None


class WorkspaceFileListResponse(BaseModel):
    files: list[WorkspaceFileInfo]
    # Trailing-slash paths for folders that should be visible even if empty
    # (currently: every project, so newly-created projects show up before any
    # file lands in their prefix).
    directories: list[str] = []


class WorkspaceFileDownloadResponse(BaseModel):
    url: str
    path: str


def _get_artifact_service() -> ArtifactService:
    return ArtifactService()


async def get_project_service(
    repository_factory: RepositoryFactoryDep,
) -> ProjectService:
    repo = repository_factory.create_repository(ProjectRepository)
    return ProjectService(repo)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.get("", response_model=WorkspaceFileListResponse)
async def list_workspace_files(
    user_context: UserContextDep,
    project_service: ProjectServiceDep,
) -> WorkspaceFileListResponse:
    svc = _get_artifact_service()
    objects = await svc.list(user_context.workspace_id)
    files = [
        WorkspaceFileInfo(
            path=obj.path,
            size=obj.size,
            content_type=obj.content_type,
            last_modified=obj.last_modified,
        )
        for obj in objects
    ]
    projects = await project_service.list()
    directories = [f"projects/{p.id}/" for p in projects]
    return WorkspaceFileListResponse(files=files, directories=directories)


@router.get("/{file_path:path}", response_model=WorkspaceFileDownloadResponse)
async def download_workspace_file(
    file_path: str,
    user_context: UserContextDep,
) -> WorkspaceFileDownloadResponse:
    svc = _get_artifact_service()
    if not await svc.exists(user_context.workspace_id, file_path):
        raise HTTPException(status_code=404, detail="File not found")
    url = await svc.presigned_url(user_context.workspace_id, file_path)
    return WorkspaceFileDownloadResponse(url=url, path=file_path)
