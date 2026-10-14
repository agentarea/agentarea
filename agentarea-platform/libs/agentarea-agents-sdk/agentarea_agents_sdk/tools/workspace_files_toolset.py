"""Workspace file operations safe to run inside the agent worker.

This toolset intentionally avoids importing ``agentarea_api``. The API process
also exposes a platform MCP tool with the same user-facing surface, but the
agent worker needs a pure SDK implementation so code-tool execution does not
depend on the API package being installed in the worker image.

``upload_urls`` exists only on the API side: it hands out presigned PUTs to MCP
clients, while an agent writes files through its sandbox instead.
"""

from __future__ import annotations

import json
from urllib.parse import quote

from .base_tool import ToolError
from .decorator_tool import Toolset, tool_method
from .file_toolset import InMemoryStorage, StorageClient, WorkspaceRepositoryClient
from .tool_authz import unrestricted
from .tool_definition import toolset


@toolset(
    namespace="agentarea/workspace_files",
    display_name="Workspace Files",
    description="List, fetch API download paths for, and delete workspace files.",
    category="platform",
    plane="runtime",
    group="sandbox",
    requires_user_confirmation=True,
)
class WorkspaceFilesToolset(Toolset):
    """Workspace-scoped file operations backed by the injected object store."""

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_repository: WorkspaceRepositoryClient | None = None,
        workspace_id: str | None = None,
        workspace_slug: str | None = None,
        task_id: str | None = None,
        lease_owner: str | None = None,
        base_prefix: str = "",
    ) -> None:
        super().__init__()
        self.storage: StorageClient = storage or InMemoryStorage()
        self.workspace_repository = workspace_repository
        if not workspace_id:
            raise ValueError(
                "workspace_id is required: storage is scoped by it, and a shared "
                "placeholder mixes one tenant's files into another's"
            )
        self.workspace_id = workspace_id
        # Download paths name the workspace by slug (/v1/workspaces/{slug}/...).
        self.workspace_slug = workspace_slug
        self.task_id = task_id or ""
        self.lease_owner = lease_owner or ""
        self.base_prefix = base_prefix.strip("/")

    def _resolve_prefix(self, prefix: str = "") -> str:
        if prefix.startswith("/"):
            raise ToolError(f"path escapes workspace scope: {prefix!r}")
        clean_prefix = prefix
        if ".." in clean_prefix.split("/") or "\\" in clean_prefix:
            raise ToolError(f"path escapes workspace scope: {prefix!r}")
        if self.workspace_repository is not None:
            return clean_prefix
        if self.base_prefix and clean_prefix:
            return f"{self.base_prefix}/{clean_prefix}"
        return self.base_prefix or clean_prefix

    def _relative(self, path: str) -> str:
        if self.base_prefix and path.startswith(self.base_prefix + "/"):
            return path[len(self.base_prefix) + 1 :]
        return path

    async def _exists(self, resolved_path: str) -> bool:
        if self.workspace_repository is not None:
            if not self.task_id:
                raise ValueError("task_id is required for canonical workspace operations")
            return await self.workspace_repository.exists(
                self.workspace_id, self.task_id, resolved_path
            )
        return await self.storage.exists(self.workspace_id, resolved_path)

    @tool_method(effect="read")
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def list(self, prefix: str = "", max_items: int = 200) -> str:
        """List files in the current workspace's storage."""
        resolved_prefix = self._resolve_prefix(prefix)
        if self.workspace_repository is not None:
            if not self.task_id:
                raise ValueError("task_id is required for canonical workspace operations")
            objects = await self.workspace_repository.list(
                self.workspace_id, self.task_id, prefix=resolved_prefix, max_items=max_items
            )
        else:
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

    @tool_method(effect="read")
    @unrestricted("workspace files are member-level, as /v1/files serves them")
    async def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Return an AgentArea API download path for a workspace file.

        A task's file is served by the task files endpoint
        (``files/download/tasks/{task_id}/workspace/{path}``) once it is saved
        to the task, e.g. as an artifact; without a task it is a library file.
        """
        resolved_path = self._resolve_prefix(path)
        if not await self._exists(resolved_path):
            raise ToolError(f"File not found: {path}")
        if not self.workspace_slug:
            raise ValueError("workspace_slug is required to build a download path")
        api_path = (
            f"tasks/{self.task_id}/workspace/{resolved_path}"
            if self.task_id
            else resolved_path.lstrip("/")
        )
        encoded_path = quote(api_path, safe="/")
        return json.dumps(
            {
                "url": f"/v1/workspaces/{self.workspace_slug}/files/download/{encoded_path}",
                "path": path,
                "expires_in": expires_in,
            }
        )

    @tool_method(effect="destructive")
    @unrestricted("workspace files are member-level, as DELETE /v1/files allows")
    async def delete(self, path: str) -> str:
        """Delete a workspace file."""
        resolved_path = self._resolve_prefix(path)
        if not await self._exists(resolved_path):
            raise ToolError(f"File not found: {path}")
        if self.workspace_repository is not None:
            await self.workspace_repository.delete(
                self.workspace_id,
                self.task_id,
                resolved_path,
                owner=self.lease_owner or None,
            )
        else:
            await self.storage.delete(self.workspace_id, resolved_path)
        return json.dumps({"deleted": True, "path": path})
