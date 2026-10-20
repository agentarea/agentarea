"""FilesToolset — workspace file storage operations."""

import builtins
import json
from typing import Annotated, Literal
from urllib.parse import quote

from agentarea_agents_sdk.tools.base_tool import ToolError
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.artifacts import (
    ArtifactActor,
    ArtifactService,
    DbArtifactEventRecorder,
    InvalidArtifactPathError,
)
from agentarea_common.artifacts.workspace_writes import (
    MAX_UPLOADS_PER_PLAN,
    WorkspaceReadOnlyError,
    ensure_not_read_only,
    plan_uploads,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.config.app import get_app_settings
from agentarea_common.workspaces.lookup import workspace_api_prefix
from pydantic import BaseModel, Field

from .base import platform_context, platform_read_context

_PATH = "Path of the file relative to the workspace root, as `workspace_files_list` returns it."


class WorkspaceFileOutput(BaseModel):
    path: str = Field(description="Path relative to the workspace root.")
    size: int = Field(description="Size in bytes.")
    content_type: str | None = Field(default=None, description="MIME type, when stored.")
    last_modified: str | None = Field(
        default=None, description="ISO 8601 time of the last write, when known."
    )


class WorkspaceFileUrlOutput(BaseModel):
    url: str = Field(description="AgentArea API URL that downloads the file with your credentials.")
    path: str = Field(description="The requested path.")
    expires_in: int = Field(description="The requested lifetime in seconds, echoed back.")


class WorkspaceFileUploadPlan(BaseModel):
    path: str = Field(description="Normalized path the file is written to.")
    status: Literal["unchanged", "upload", "error"] = Field(
        description="unchanged: same bytes already stored; upload: PUT them to upload_url; "
        "error: see error."
    )
    error: str | None = Field(default=None, description="Why the entry cannot be written.")
    upload_url: str | None = Field(default=None, description="Presigned URL to PUT the bytes to.")
    method: Literal["PUT"] | None = Field(default=None, description="HTTP method for upload_url.")
    headers: dict[str, str] | None = Field(
        default=None, description="Headers the PUT must carry, exactly as given."
    )
    expires_in: int | None = Field(default=None, description="Seconds upload_url stays valid.")


class WorkspaceFileUploadsOutput(BaseModel):
    uploads: builtins.list[WorkspaceFileUploadPlan] = Field(
        description="One entry per requested file, in request order."
    )


class WorkspaceFileDeletedOutput(BaseModel):
    deleted: bool = Field(description="True once the file is gone.")
    path: str = Field(description="The deleted path.")


async def _workspace_file_download_url(user_context: UserContext, path: str) -> str:
    base = get_app_settings().API_URL.rstrip("/")
    encoded_path = quote(path.lstrip("/"), safe="/")
    return f"{base}{await workspace_api_prefix(user_context)}/files/download/{encoded_path}"


async def _exists(svc: ArtifactService, workspace_id: str, path: str) -> bool:
    try:
        return await svc.exists(workspace_id, path)
    except InvalidArtifactPathError:
        return False


@toolset(
    namespace="agentarea/workspace_files",
    display_name="Workspace Files",
    description="List, upload, fetch download URLs for, and delete workspace files.",
    category="platform",
    plane="operate",
    requires_user_confirmation=True,
    register=False,
)
class FilesToolset(Toolset):
    """List, upload, fetch download URLs for, and delete workspace files."""

    open_world = False

    @tool_method(
        display_name="List workspace files", effect="read", output=list[WorkspaceFileOutput]
    )
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def list(
        self,
        prefix: Annotated[
            str,
            Field(
                description="Only files whose path starts with this, e.g. `reports/`; empty for all."
            ),
        ] = "",
        max_items: Annotated[int, Field(description="Maximum number of files to return.")] = 200,
    ) -> str:
        """List files in the current workspace's storage."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService()
            objects = await svc.list(user_ctx.workspace_id, prefix=prefix, max_items=max_items)
            return json.dumps(
                [
                    {
                        "path": obj.path,
                        "size": obj.size,
                        "content_type": obj.content_type,
                        "last_modified": obj.last_modified,
                    }
                    for obj in objects
                ],
                default=str,
            )

    @tool_method(
        display_name="Get workspace file URL", effect="read", output=WorkspaceFileUrlOutput
    )
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def get_url(
        self,
        path: Annotated[str, Field(description=_PATH)],
        expires_in: Annotated[
            int, Field(description="Requested link lifetime in seconds; echoed in the result.")
        ] = 3600,
    ) -> str:
        """Get an AgentArea API download URL for a workspace file."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService()
            if not await _exists(svc, user_ctx.workspace_id, path):
                raise ToolError("File not found")
            url = await _workspace_file_download_url(user_ctx, path)
            return json.dumps({"url": url, "path": path, "expires_in": expires_in})

    @tool_method(
        display_name="Get workspace file upload URLs",
        effect="write",
        output=WorkspaceFileUploadsOutput,
    )
    @unrestricted("workspace files are member-level, as POST /v1/files/upload-urls allows")
    async def upload_urls(
        self,
        files: Annotated[
            builtins.list[dict[str, str]],
            Field(
                description='Files to write, 1-100 entries of {"path": str, "sha256": str, '
                '"content_type"?: str}: path relative to the workspace root, sha256 the '
                "lowercase hex digest of the bytes."
            ),
        ],
    ) -> str:
        """Get presigned PUT URLs that write files into workspace storage.

        Each entry is ``{"path", "sha256", "content_type"?}``, where ``sha256``
        is the file's lowercase hex digest; at most 100 per call. Every entry
        comes back with a ``status``: ``unchanged`` when the same bytes are
        already stored, ``upload`` with an ``upload_url`` to PUT the bytes to
        using the returned ``method`` and ``headers`` (the store rejects a body
        that does not hash to ``sha256``), or ``error``. To sync a whole
        folder, prefer ``agentarea files sync`` from a shell: it hashes locally
        and keeps the URLs out of the conversation.
        """
        if not files:
            raise ToolError("files must not be empty")
        if len(files) > MAX_UPLOADS_PER_PLAN:
            raise ToolError(f"at most {MAX_UPLOADS_PER_PLAN} files per call")
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService(
                recorder=DbArtifactEventRecorder(),
                actor=ArtifactActor(user_id=user_ctx.user_id),
            )
            results = await plan_uploads(svc, user_ctx.workspace_id, files)
        return json.dumps({"uploads": results})

    @tool_method(
        display_name="Delete workspace file",
        effect="destructive",
        idempotent=True,
        output=WorkspaceFileDeletedOutput,
    )
    @unrestricted("workspace files are member-level, as DELETE /v1/files allows")
    async def delete(self, path: Annotated[str, Field(description=_PATH)]) -> str:
        """Delete a workspace file."""
        try:
            ensure_not_read_only(path)
        except WorkspaceReadOnlyError as exc:
            raise ToolError(str(exc)) from exc
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService()
            if not await _exists(svc, user_ctx.workspace_id, path):
                raise ToolError("File not found")
            await svc.delete(user_ctx.workspace_id, path)
            return json.dumps({"deleted": True, "path": path})
