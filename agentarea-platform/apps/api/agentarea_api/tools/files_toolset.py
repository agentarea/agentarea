"""FilesToolset — workspace file storage operations."""

import json
from urllib.parse import quote

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset
from agentarea_common.config.app import get_app_settings

from .base import platform_context, platform_read_context


def _workspace_file_download_url(path: str) -> str:
    base = get_app_settings().API_BASE_URL.rstrip("/")
    encoded_path = quote(path.lstrip("/"), safe="/")
    return f"{base}/v1/files/download/{encoded_path}"


@toolset(
    namespace="agentarea/workspace_files",
    display_name="Workspace Files",
    description="List, fetch download URLs for, and delete workspace files.",
    category="platform",
    requires_user_confirmation=True,
)
class FilesToolset(Toolset):
    """List, fetch download URLs for, and delete workspace files."""

    @tool_method
    async def list(self, prefix: str = "", max_items: int = 200) -> str:
        """List files in the current workspace's storage."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            from agentarea_common.artifacts import ArtifactService

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

    @tool_method
    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get an AgentArea API download URL for a workspace file."""
        async with platform_read_context() as (_session, user_ctx, _repo, _broker, _secret):
            from agentarea_common.artifacts import ArtifactService

            svc = ArtifactService()
            if not await svc.exists(user_ctx.workspace_id, path):
                return json.dumps({"error": "File not found"})
            url = _workspace_file_download_url(path)
            return json.dumps({"url": url, "path": path, "expires_in": expires_in})

    @tool_method
    async def delete(self, path: str) -> str:
        """Delete a workspace file."""
        async with platform_context() as (_session, user_ctx, _repo, _broker, _secret):
            from agentarea_common.artifacts import ArtifactService

            svc = ArtifactService()
            if not await svc.exists(user_ctx.workspace_id, path):
                return json.dumps({"deleted": False, "error": "File not found"})
            await svc.delete(user_ctx.workspace_id, path)
            return json.dumps({"deleted": True, "path": path})
