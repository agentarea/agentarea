"""Workspace-scoped files API.

Lists and serves the files stored under the current workspace's S3 prefix.
Files end up here from any source — agent tool runs, task artifacts, manual
uploads from a project. Task workspace paths are resolved through committed
manifests; raw manifests and immutable-object keys are never exposed here.

Only the workspace library is writable through this router, and deletes are
archives: the object moves under ``.trash/`` rather than being destroyed.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated
from urllib.parse import quote
from uuid import uuid4

from agentarea_api.api.deps.database import ReadDatabaseSessionDep
from agentarea_common.artifacts import (
    TRASH_PREFIX,
    ArtifactActor,
    ArtifactEvent,
    ArtifactIntegrityError,
    ArtifactService,
    DbArtifactEventRecorder,
    WorkspaceRepository,
    WorkspaceValidationError,
    normalize_workspace_path,
)
from agentarea_common.artifacts.workspace import DEFAULT_MAX_FILE_BYTES
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.config.app import get_app_settings
from agentarea_projects.application.service import ProjectService
from agentarea_projects.infrastructure.repository import ProjectRepository
from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

logger = logging.getLogger(__name__)

# Server-proxied attachment uploads are buffered in memory to verify their size
# and digest, so cap them at the same per-file ceiling the task workspace
# enforces. The presigned path re-checks size/quota at attach time.
MAX_ATTACHMENT_BYTES = DEFAULT_MAX_FILE_BYTES
_SHA256_HEX_RE = re.compile(r"^[0-9a-f]{64}$")


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
    # Trailing-slash paths keep user-created and project folders visible when empty.
    directories: list[str] = Field(default_factory=list)


class CreateWorkspaceDirectoryRequest(BaseModel):
    path: str = Field(..., min_length=1)

    model_config = {"extra": "forbid"}


class WorkspaceDirectoryResponse(BaseModel):
    path: str


class WorkspaceFileDownloadResponse(BaseModel):
    url: str
    path: str


class StagedFileResponse(BaseModel):
    ref: str
    filename: str
    size: int
    sha256: str
    content_type: str | None = None


class PresignUploadRequest(BaseModel):
    filename: str = Field(..., min_length=1)
    content_type: str = Field(..., min_length=1)
    sha256: str
    size: int

    model_config = {"extra": "forbid"}


class PresignUploadResponse(BaseModel):
    ref: str
    upload_url: str
    expires_in: int


class MoveWorkspaceFileRequest(BaseModel):
    source: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)

    model_config = {"extra": "forbid"}


class MovedFileResponse(BaseModel):
    source: str
    destination: str
    moved: int


class ArchivedFileResponse(BaseModel):
    path: str
    archived_path: str


class RestoredFileResponse(BaseModel):
    path: str
    restored_from: str


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


def _is_hidden_storage_path(file_path: str) -> bool:
    """Paths the workspace view never shows and manual writes may never touch.

    ``staging/`` holds half-finished attachment uploads, ``tasks/`` is the
    task-owned surface reached through committed manifests, and ``.trash/``
    holds archived files that only the restore endpoint may resurrect.
    """
    clean = file_path.lstrip("/")
    parts = PurePosixPath(clean).parts
    return bool(parts and parts[0] in {"tasks", "staging", TRASH_PREFIX.rstrip("/")})


def _resolve_upload_path(path: str, filename: str) -> str:
    """Resolve where an upload lands, rejecting anything outside the workspace.

    An explicit ``path`` keeps the directory structure the client sent, which is
    what makes folder uploads and prefix-scoped reads possible. Without one the
    file lands at the workspace root under its own name.
    """
    if not path:
        path = PurePosixPath(filename or "unnamed").name or "unnamed"
    try:
        resolved = normalize_workspace_path(path)
    except WorkspaceValidationError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if _is_hidden_storage_path(resolved):
        raise HTTPException(
            status_code=422,
            detail=f"{resolved!r} is a reserved prefix and cannot be written directly",
        )
    return resolved


async def _ensure_no_file_ancestors(service: ArtifactService, workspace_id: str, path: str) -> None:
    """Prevent an existing file from also becoming a parent folder."""
    for parent in PurePosixPath(path).parents:
        if parent != PurePosixPath(".") and await service.exists(workspace_id, str(parent)):
            raise HTTPException(status_code=409, detail=f"A file already exists at {str(parent)!r}")


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


@router.get(
    "",
    response_model=WorkspaceFileListResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def list_workspace_files(
    user_context: UserContextDep,
    project_service: ProjectServiceDep,
) -> WorkspaceFileListResponse:
    """List the files a person put in the workspace.

    What a task produced is not among them: a task's files belong to that run
    and are browsed on the task itself, so they stay out of the workspace view
    even though ``tasks/{id}/workspace/{path}`` remains readable by that name.
    """
    svc = _get_artifact_service()
    objects = await svc.list(user_context.workspace_id)
    visible_objects = [obj for obj in objects if not _is_hidden_storage_path(obj.path)]
    files = [
        WorkspaceFileInfo(
            path=obj.path,
            size=obj.size,
            content_type=obj.content_type,
            last_modified=obj.last_modified,
        )
        for obj in visible_objects
        if not obj.path.endswith("/")
    ]
    projects = await project_service.list()
    directories = sorted(
        {obj.path for obj in visible_objects if obj.path.endswith("/")}
        | {f"projects/{p.id}/" for p in projects}
    )
    return WorkspaceFileListResponse(files=files, directories=directories)


@router.post(
    "/directories",
    status_code=201,
    response_model=WorkspaceDirectoryResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_workspace_directory(
    body: CreateWorkspaceDirectoryRequest,
    user_context: UserContextDep,
    project_service: ProjectServiceDep,
) -> WorkspaceDirectoryResponse:
    """Persist an empty workspace folder as a trailing-slash object marker."""
    # Accept the same trailing-slash convention returned by the listing, but
    # strip only one slash so repeated separators still fail validation.
    requested_path = body.path.removesuffix("/")
    if not requested_path:
        raise HTTPException(status_code=422, detail="Folder path must not be empty")
    path = _resolve_upload_path(requested_path, "")
    directory_path = f"{path}/"
    workspace_id = user_context.workspace_id
    service = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    await _ensure_no_file_ancestors(service, workspace_id, path)
    if await service.exists(workspace_id, path):
        raise HTTPException(status_code=409, detail=f"A file already exists at {path!r}")
    projects = await project_service.list()
    if any(f"projects/{project.id}/".startswith(directory_path) for project in projects):
        raise HTTPException(status_code=409, detail="A folder already exists at this path")
    if await service.list(workspace_id, prefix=directory_path, max_items=1):
        raise HTTPException(status_code=409, detail="A folder already exists at this path")
    await service.put(workspace_id, directory_path, b"", content_type="application/x-directory")
    return WorkspaceDirectoryResponse(path=directory_path)


@router.post(
    "",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def upload_file(
    file: UploadFile,
    user_context: UserContextDep,
    purpose: Annotated[str, Form()] = "workspace",
    path: Annotated[str, Form()] = "",
):
    """Upload a file, server-proxied.

    ``purpose="workspace"`` (the default) lands the file at ``path`` within the
    workspace, or at the workspace root under its own name when ``path`` is
    omitted. ``purpose="attachment"`` stages it under ``staging/{id}/{filename}``
    — hidden from the workspace listing — and returns a ``ref`` the task-create
    endpoint resolves into the task workspace.
    """
    filename = PurePosixPath(file.filename or "unnamed").name or "unnamed"
    content = await file.read()
    svc = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    if purpose == "workspace":
        resolved_path = _resolve_upload_path(path, filename)
        await _ensure_no_file_ancestors(svc, user_context.workspace_id, resolved_path)
        if await svc.list(user_context.workspace_id, prefix=f"{resolved_path}/", max_items=1):
            raise HTTPException(status_code=409, detail="A folder already exists at this path")
        await svc.put(
            user_context.workspace_id,
            resolved_path,
            content,
            content_type=file.content_type,
        )
        return Response(status_code=204)
    if purpose == "attachment":
        if len(content) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte per-file limit",
            )
        path = f"staging/{uuid4().hex}/{filename}"
        await svc.put(
            user_context.workspace_id,
            path,
            content,
            content_type=file.content_type,
        )
        return StagedFileResponse(
            ref=path,
            filename=filename,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            content_type=file.content_type,
        )
    raise HTTPException(status_code=422, detail=f"Unsupported upload purpose: {purpose!r}")


@router.post(
    "/upload-url",
    response_model=PresignUploadResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def create_attachment_upload_url(
    body: PresignUploadRequest,
    user_context: UserContextDep,
) -> PresignUploadResponse:
    """Mint a presigned PUT for a task attachment uploaded directly to the store.

    The client-declared sha256 is bound into the signature as ``ChecksumSHA256``,
    so the object store rejects a body that does not hash to it — the upload is
    content-verified without the API ever seeing the bytes. The returned ``ref``
    is consumed by the task-create endpoint exactly like a server-proxied one.
    """
    if not _SHA256_HEX_RE.fullmatch(body.sha256):
        raise HTTPException(
            status_code=422, detail="sha256 must be a 64-character lowercase hex digest"
        )
    if body.size < 0:
        raise HTTPException(status_code=422, detail="size must be a non-negative integer")
    if body.size > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"attachment exceeds the {MAX_ATTACHMENT_BYTES}-byte per-file limit",
        )
    filename = PurePosixPath(body.filename or "unnamed").name or "unnamed"
    path = f"staging/{uuid4().hex}/{filename}"
    expires_in = 3600
    sha256_b64 = base64.b64encode(bytes.fromhex(body.sha256)).decode("ascii")
    upload_url = await _get_artifact_service().presigned_put_url(
        user_context.workspace_id,
        path,
        content_type=body.content_type,
        sha256_b64=sha256_b64,
        expires_in=expires_in,
    )
    return PresignUploadResponse(ref=path, upload_url=upload_url, expires_in=expires_in)


@router.post(
    "/move",
    response_model=MovedFileResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def move_workspace_file(
    body: MoveWorkspaceFileRequest,
    user_context: UserContextDep,
) -> MovedFileResponse:
    """Relocate a workspace file or folder to another path.

    A folder is a key prefix rather than an object, so moving one walks every
    key beneath it — including the trailing-slash marker that keeps an empty
    folder visible in the listing. Reserved prefixes are refused at both ends:
    ``tasks/`` belongs to a task's committed manifest, and ``.trash/`` is the
    restore endpoint's alone.
    """
    source = _resolve_upload_path(body.source.removesuffix("/"), "")
    destination = _resolve_upload_path(body.destination.removesuffix("/"), "")
    if source == destination:
        raise HTTPException(status_code=422, detail="Source and destination are the same")
    if destination.startswith(f"{source}/"):
        raise HTTPException(status_code=422, detail="Cannot move a folder into itself")

    workspace_id = user_context.workspace_id
    svc = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    await _ensure_no_file_ancestors(svc, workspace_id, destination)
    if await svc.exists(workspace_id, destination):
        raise HTTPException(status_code=409, detail=f"A file already exists at {destination!r}")
    if await svc.list(workspace_id, prefix=f"{destination}/", max_items=1):
        raise HTTPException(status_code=409, detail="A folder already exists at this path")

    if await svc.exists(workspace_id, source):
        await svc.move(workspace_id, source, destination)
        return MovedFileResponse(source=source, destination=destination, moved=1)

    contents = await svc.list(workspace_id, prefix=f"{source}/")
    if not contents:
        raise HTTPException(status_code=404, detail="File not found")
    for obj in contents:
        await svc.move(workspace_id, obj.path, f"{destination}/{obj.path[len(source) + 1 :]}")
    return MovedFileResponse(source=source, destination=destination, moved=len(contents))


@router.delete(
    "/{file_path:path}",
    response_model=ArchivedFileResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def delete_workspace_file(
    file_path: str,
    user_context: UserContextDep,
) -> ArchivedFileResponse:
    """Archive a workspace file instead of destroying it.

    The object moves under ``.trash/{timestamp}/`` and disappears from the
    listing, so a mistaken delete is always recoverable through
    :func:`restore_workspace_file`. Task-owned and staging paths are not
    deletable here: they belong to a task's committed manifest, not to the
    workspace library.
    """
    clean = file_path.lstrip("/")
    if _is_hidden_storage_path(clean):
        raise HTTPException(
            status_code=400,
            detail=f"{clean!r} is not a workspace library file",
        )
    svc = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    if not await svc.exists(user_context.workspace_id, clean):
        raise HTTPException(status_code=404, detail="File not found")
    archived_path = await svc.archive(user_context.workspace_id, clean)
    return ArchivedFileResponse(path=clean, archived_path=archived_path)


@router.post(
    "/restore/{file_path:path}",
    response_model=RestoredFileResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
async def restore_workspace_file(
    file_path: str,
    user_context: UserContextDep,
) -> RestoredFileResponse:
    """Move an archived file back to the path it was archived from."""
    clean = file_path.lstrip("/")
    if not clean.startswith(TRASH_PREFIX):
        raise HTTPException(status_code=400, detail="Not an archived file")
    # .trash/{timestamp}/{original path} — drop the two-segment archive header.
    original = "/".join(PurePosixPath(clean).parts[2:])
    if not original:
        raise HTTPException(status_code=400, detail="Archived path carries no original path")
    svc = ArtifactService(
        recorder=DbArtifactEventRecorder(),
        actor=ArtifactActor(user_id=user_context.user_id),
    )
    await svc.copy(user_context.workspace_id, clean, original)
    await svc.delete(user_context.workspace_id, clean)
    return RestoredFileResponse(path=original, restored_from=clean)


@router.get(
    "/history",
    response_model=ArtifactHistoryResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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


@router.get(
    "/download/{file_path:path}",
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
            if _is_hidden_storage_path(file_path):
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


@router.get(
    "/{file_path:path}",
    response_model=WorkspaceFileDownloadResponse,
    dependencies=[
        unrestricted("workspace member; the workspace-scoped repository is the boundary")
    ],
)
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
            exists = not _is_hidden_storage_path(
                file_path
            ) and await _get_artifact_service().exists(user_context.workspace_id, file_path)
    except WorkspaceValidationError:
        exists = False
    if not exists:
        raise HTTPException(status_code=404, detail="File not found")
    url = _workspace_file_download_url(file_path)
    return WorkspaceFileDownloadResponse(url=url, path=file_path)
