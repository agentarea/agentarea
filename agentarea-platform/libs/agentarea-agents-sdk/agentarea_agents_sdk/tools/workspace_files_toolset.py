"""Workspace file operations safe to run inside the agent worker.

This toolset intentionally avoids importing ``agentarea_api``. The API process
also exposes a platform MCP tool with the same user-facing surface, but the
agent worker needs a pure SDK implementation so code-tool execution does not
depend on the API package being installed in the worker image.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from .decorator_tool import Toolset, tool_method
from .file_toolset import InMemoryStorage, StorageClient
from .tool_definition import toolset


@toolset(
    namespace="agentarea/workspace_files",
    display_name="Workspace Files",
    description="List, fetch API download paths for, and delete workspace files.",
    category="platform",
    requires_user_confirmation=True,
)
class WorkspaceFilesToolset(Toolset):
    """Workspace-scoped file operations backed by the injected object store."""

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_id: str | None = None,
        base_prefix: str = "",
    ) -> None:
        super().__init__()
        self.storage: StorageClient = storage or InMemoryStorage()
        self.workspace_id = workspace_id or "_standalone"
        self.base_prefix = base_prefix.strip("/")

    def _resolve_prefix(self, prefix: str = "") -> str:
        clean_prefix = prefix.lstrip("/")
        if ".." in clean_prefix.split("/"):
            raise ValueError(f"path escapes workspace scope: {prefix!r}")
        if self.base_prefix and clean_prefix:
            return f"{self.base_prefix}/{clean_prefix}"
        return self.base_prefix or clean_prefix

    def _relative(self, path: str) -> str:
        if self.base_prefix and path.startswith(self.base_prefix + "/"):
            return path[len(self.base_prefix) + 1 :]
        return path

    @tool_method
    async def list(self, prefix: str = "", max_items: int = 200) -> str:
        """List files in the current workspace's storage."""
        try:
            resolved_prefix = self._resolve_prefix(prefix)
            objects = await self.storage.list(self.workspace_id, prefix=resolved_prefix)
            rows = []
            for obj in objects[: max(0, max_items)]:
                path = str(
                    getattr(obj, "path", None) or (obj.get("path") if isinstance(obj, dict) else "")
                )
                rows.append(
                    {
                        "path": self._relative(path),
                        "size": getattr(obj, "size", None)
                        or (obj.get("size") if isinstance(obj, dict) else None),
                        "content_type": getattr(obj, "content_type", None)
                        or (obj.get("content_type") if isinstance(obj, dict) else None),
                    }
                )
            return json.dumps(rows, default=str)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @tool_method
    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Return an AgentArea API download path for a workspace file."""
        try:
            resolved_path = self._resolve_prefix(path)
            if not await self.storage.exists(self.workspace_id, resolved_path):
                return json.dumps({"error": "File not found", "path": path})
            encoded_path = quote(resolved_path.lstrip("/"), safe="/")
            return json.dumps(
                {
                    "url": f"/v1/files/download/{encoded_path}",
                    "path": path,
                    "expires_in": expires_in,
                }
            )
        except Exception as exc:
            return json.dumps({"error": str(exc), "path": path})

    @tool_method
    async def delete(self, path: str) -> str:
        """Delete a workspace file."""
        try:
            resolved_path = self._resolve_prefix(path)
            if not await self.storage.exists(self.workspace_id, resolved_path):
                return json.dumps({"deleted": False, "error": "File not found"})
            await self.storage.delete(self.workspace_id, resolved_path)
            return json.dumps({"deleted": True, "path": path})
        except Exception as exc:
            return json.dumps({"deleted": False, "error": str(exc), "path": path})
