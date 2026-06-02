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
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote

from agentarea_api.api.deps.database import ReadDatabaseSessionDep
from agentarea_common.artifacts import ArtifactEvent, ArtifactService
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config.app import get_app_settings
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

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


class ArtifactEventResponse(BaseModel):
    action: str
    actor_type: str
    created_by: str
    agent_id: str | None = None
    task_id: str | None = None
    created_at: str


class ArtifactHistoryResponse(BaseModel):
    path: str
    events: list[ArtifactEventResponse]


def _get_artifact_service() -> ArtifactService:
    return ArtifactService()


def _workspace_file_download_url(file_path: str) -> str:
    base = get_app_settings().API_BASE_URL.rstrip("/")
    encoded_path = quote(file_path.lstrip("/"), safe="/")
    return f"{base}/v1/files/download/{encoded_path}"


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


@router.get("/history", response_model=ArtifactHistoryResponse)
async def workspace_file_history(
    path: str,
    user_context: UserContextDep,
    session: ReadDatabaseSessionDep,
) -> ArtifactHistoryResponse:
    """Return the provenance trail for a workspace file, newest event first."""
    clean = path.lstrip("/")
    stmt = (
        select(ArtifactEvent)
        .where(ArtifactEvent.workspace_id == user_context.workspace_id)
        .where(ArtifactEvent.path == clean)
        .order_by(ArtifactEvent.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    events = [
        ArtifactEventResponse(
            action=ev.action,
            actor_type=ev.actor_type,
            created_by=ev.created_by,
            agent_id=ev.agent_id,
            task_id=ev.task_id,
            created_at=ev.created_at.isoformat(),
        )
        for ev in rows
    ]
    return ArtifactHistoryResponse(path=clean, events=events)


@router.get("/download/{file_path:path}")
async def stream_workspace_file(
    file_path: str,
    user_context: UserContextDep,
):
    """Stream a workspace file through the AgentArea API."""
    svc = _get_artifact_service()
    try:
        data, content_type = await svc.get(user_context.workspace_id, file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found") from None

    filename = PurePosixPath(file_path).name or "file.bin"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(iter([data]), media_type=content_type, headers=headers)


@router.get("/{file_path:path}", response_model=WorkspaceFileDownloadResponse)
async def download_workspace_file(
    file_path: str,
    user_context: UserContextDep,
) -> WorkspaceFileDownloadResponse:
    svc = _get_artifact_service()
    if not await svc.exists(user_context.workspace_id, file_path):
        raise HTTPException(status_code=404, detail="File not found")
    url = _workspace_file_download_url(file_path)
    return WorkspaceFileDownloadResponse(url=url, path=file_path)
