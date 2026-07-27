"""Workspace-scoped files API.

Lists and serves the files stored under the current workspace's S3 prefix.
Files end up here from any source — agent tool runs, task artifacts, manual
uploads from a project — so this is a read-only window into whatever the
workspace already owns. Task workspace paths are resolved through committed
manifests; raw manifests and immutable-object keys are never exposed here.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from agentarea_api.api.deps.database import ReadDatabaseSessionDep
from agentarea_common.artifacts import (
    ArtifactActor,
    ArtifactEvent,
    ArtifactIntegrityError,
    ArtifactService,
    DbArtifactEventRecorder,
    WorkspaceRepository,
    WorkspaceValidationError,
    normalize_workspace_path,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config.app import get_app_settings
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

logger = logging.getLogger(__name__)


def _attachment_content_disposition(filename: str) -> str:
    fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", fallback).strip("._-") or "file.bin"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


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


class StagedFileResponse(BaseModel):
    ref: str
    filename: str
    size: int
    content_type: str | None = None


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


def _get_workspace_repository() -> WorkspaceRepository:
    return WorkspaceRepository()


def _task_workspace_path(file_path: str) -> tuple[str, str] | None:
    """Parse the public ``tasks/{id}/workspace/{path}`` logical namespace."""
    clean = file_path.lstrip("/")
    parts = PurePosixPath(clean).parts
    if len(parts) < 4 or parts[0] != "tasks" or parts[2] != "workspace":
        return None
    if clean != "/".join(parts) or "\\" in clean:
        raise WorkspaceValidationError("workspace path is not canonical")
    relative_path = normalize_workspace_path("/".join(parts[3:]))
    return parts[1], relative_path


def _is_task_storage_path(file_path: str) -> bool:
    clean = file_path.lstrip("/")
    if clean.startswith("staging/"):
        return True
    parts = PurePosixPath(clean).parts
    return bool(parts and parts[0] == "tasks")


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
    visible_objects = [obj for obj in objects if not _is_task_storage_path(obj.path)]
    files = [
        WorkspaceFileInfo(
            path=obj.path,
            size=obj.size,
            content_type=obj.content_type,
            last_modified=obj.last_modified,
        )
        for obj in visible_objects
    ]
    workspace_repository = _get_workspace_repository()
    task_ids = await workspace_repository.list_task_ids(user_context.workspace_id)
    for task_id in task_ids:
        for obj in await workspace_repository.list(user_context.workspace_id, task_id):
            files.append(
                WorkspaceFileInfo(
                    path=f"tasks/{task_id}/workspace/{obj.path}",
                    size=obj.size,
                    content_type=obj.content_type,
                )
            )
    projects = await project_service.list()
    directories = [f"projects/{p.id}/" for p in projects]
    return WorkspaceFileListResponse(files=files, directories=directories)


@router.post("", status_code=204)
async def upload_workspace_file(
    file: UploadFile,
    user_context: UserContextDep,
):
    """Upload a file to the workspace's artifact root."""
    svc = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    # Strip any directory components so an upload can't land in another prefix.
    filename = PurePosixPath(file.filename or "unnamed").name or "unnamed"
    content = await file.read()
    await svc.put(
        user_context.workspace_id,
        filename,
        content,
        content_type=file.content_type,
    )


@router.post("/staging", response_model=StagedFileResponse)
async def upload_staging_file(
    file: UploadFile,
    user_context: UserContextDep,
) -> StagedFileResponse:
    """Stage a file for a not-yet-created task, referenced by ref in the task body.

    Staging keys live under ``staging/{id}/{filename}`` and are hidden from the
    workspace file listing; the task-create endpoint consumes and deletes them.
    """
    staging_id = uuid4().hex
    filename = PurePosixPath(file.filename or "unnamed").name or "unnamed"
    content = await file.read()
    path = f"staging/{staging_id}/{filename}"
    await ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    ).put(
        user_context.workspace_id,
        path,
        content,
        content_type=file.content_type,
    )
    return StagedFileResponse(
        ref=path,
        filename=filename,
        size=len(content),
        content_type=file.content_type,
    )


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
    try:
        parsed = _task_workspace_path(file_path)
        if parsed is not None:
            task_id, relative_path = parsed
            body, content_type, size = await _get_workspace_repository().stream(
                user_context.workspace_id, task_id, relative_path
            )
        else:
            if _is_task_storage_path(file_path):
                raise FileNotFoundError(file_path)
            body, content_type, size = await _get_artifact_service().stream(
                user_context.workspace_id, file_path
            )
    except (ArtifactIntegrityError, FileNotFoundError, WorkspaceValidationError):
        raise HTTPException(status_code=404, detail="File not found") from None

    filename = PurePosixPath(file_path).name or "file.bin"
    headers = {
        "Content-Disposition": _attachment_content_disposition(filename),
        "Content-Length": str(size),
    }
    return StreamingResponse(body, media_type=content_type, headers=headers)


@router.get("/{file_path:path}", response_model=WorkspaceFileDownloadResponse)
async def download_workspace_file(
    file_path: str,
    user_context: UserContextDep,
) -> WorkspaceFileDownloadResponse:
    try:
        parsed = _task_workspace_path(file_path)
        if parsed is not None:
            task_id, relative_path = parsed
            exists = await _get_workspace_repository().exists(
                user_context.workspace_id, task_id, relative_path
            )
        else:
            exists = not _is_task_storage_path(file_path) and await _get_artifact_service().exists(
                user_context.workspace_id, file_path
            )
    except WorkspaceValidationError:
        exists = False
    if not exists:
        raise HTTPException(status_code=404, detail="File not found")
    url = _workspace_file_download_url(file_path)
    return WorkspaceFileDownloadResponse(url=url, path=file_path)
