"""FilesToolset — workspace file storage operations."""

import builtins
import json
from urllib.parse import quote

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import unrestricted
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.artifacts import (
    ArtifactActor,
    ArtifactService,
    DbArtifactEventRecorder,
    InvalidArtifactPathError,
)
from agentarea_common.artifacts.workspace_writes import MAX_UPLOADS_PER_PLAN, plan_uploads
from agentarea_common.auth.context import UserContext
from agentarea_common.config.app import get_app_settings
from agentarea_common.workspaces.lookup import workspace_api_prefix

from .base import platform_context, platform_read_context


async def _workspace_file_download_url(user_context: UserContext, path: str) -> str:
    base = get_app_settings().API_BASE_URL.rstrip("/")
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

    @tool_method(effect="read")
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def list(self, prefix: str = "", max_items: int = 200) -> str:
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

    @tool_method(effect="read")
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get an AgentArea API download URL for a workspace file."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService()
            if not await _exists(svc, user_ctx.workspace_id, path):
                return json.dumps({"error": "File not found"})
            url = await _workspace_file_download_url(user_ctx, path)
            return json.dumps({"url": url, "path": path, "expires_in": expires_in})

    @tool_method(effect="write")
    @unrestricted("workspace files are member-level, as POST /v1/files/upload-urls allows")
    async def upload_urls(self, files: builtins.list[dict[str, str]]) -> str:
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
            return json.dumps({"error": "files must not be empty"})
        if len(files) > MAX_UPLOADS_PER_PLAN:
            return json.dumps({"error": f"at most {MAX_UPLOADS_PER_PLAN} files per call"})
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService(
                recorder=DbArtifactEventRecorder(),
                actor=ArtifactActor(user_id=user_ctx.user_id),
            )
            results = await plan_uploads(svc, user_ctx.workspace_id, files)
        return json.dumps({"uploads": results})

    @tool_method(effect="destructive")
    @unrestricted("workspace files are member-level, as DELETE /v1/files allows")
    async def delete(self, path: str) -> str:
        """Delete a workspace file."""
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            svc = ArtifactService()
            if not await _exists(svc, user_ctx.workspace_id, path):
                return json.dumps({"deleted": False, "error": "File not found"})
            await svc.delete(user_ctx.workspace_id, path)
            return json.dumps({"deleted": True, "path": path})
