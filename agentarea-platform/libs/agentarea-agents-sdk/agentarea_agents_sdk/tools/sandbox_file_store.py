"""StorageClient backed by the manager-owned live sandbox file API.

The file and shell tools share the same ephemeral ``/workspace`` filesystem.
Durable inputs are materialized there by the Go manager and selected outputs are
published separately through the artifact tool. This client carries only the
dedicated internal file-service credential; runner activation credentials never
reach Python or an agent command.

It implements the ``StorageClient`` protocol consumed by
:class:`agentarea_agents_sdk.tools.file_toolset.FileToolset`.
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from .file_toolset import StoredObject


class SandboxFileStore:
    """Workspace/task-scoped file store over the sandbox control-plane API."""

    def __init__(
        self,
        *,
        mcp_manager_url: str,
        workspace_id: str,
        task_id: str,
        auth_secret: str,
        timeout_seconds: float = 300.0,
        http_client: Any = None,
    ) -> None:
        base = (mcp_manager_url or "").rstrip("/")
        if not base:
            raise ValueError("mcp_manager_url is required for the sandbox file store")
        if not workspace_id:
            raise ValueError("workspace_id is required for the sandbox file store")
        if not task_id:
            raise ValueError("task_id is required for the sandbox file store")
        if not auth_secret:
            raise ValueError("auth_secret is required for the sandbox file store")
        self._base = base
        self._workspace_id = workspace_id
        self._task_id = task_id
        self._auth_secret = auth_secret
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _require_bound_workspace(self, workspace_id: str) -> str:
        if workspace_id != self._workspace_id:
            raise ValueError("sandbox file store is bound to a different workspace")
        return self._workspace_id

    async def put(
        self,
        workspace_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        params = {
            "workspace_id": self._require_bound_workspace(workspace_id),
            "task_id": self._task_id,
            "path": path,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "mode": "600",
        }
        response = await self._request("PUT", stream=True, params=params, content=data)
        if response.status_code >= 400:
            raise RuntimeError(
                f"sandbox file put failed for {path!r}: HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        return StoredObject(
            path=str(body.get("path", path)),
            size=int(body.get("size", len(data))),
            content_type=content_type,
        )

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        response = await self._request(
            "GET",
            stream=True,
            params={
                "workspace_id": self._require_bound_workspace(workspace_id),
                "task_id": self._task_id,
                "path": path,
            },
        )
        if response.status_code == 404:
            raise FileNotFoundError(path)
        if response.status_code >= 400:
            raise RuntimeError(
                f"sandbox file get failed for {path!r}: HTTP {response.status_code}: {response.text}"
            )
        return bytes(response.content), response.headers.get("content-type")

    async def exists(self, workspace_id: str, path: str) -> bool:
        return any(item.path == path for item in await self.list(workspace_id, path))

    async def list(self, workspace_id: str, prefix: str = "") -> list[StoredObject]:
        response = await self._request(
            "GET",
            params={
                "workspace_id": self._require_bound_workspace(workspace_id),
                "task_id": self._task_id,
                "list": prefix,
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(
                f"sandbox file list failed: HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        return [StoredObject(path=str(p), size=0) for p in body.get("paths", [])]

    async def delete(self, workspace_id: str, path: str) -> None:
        # The executor exposes no delete endpoint yet; fail loudly rather than
        # pretend a delete succeeded. The file tool never calls this today.
        raise NotImplementedError("sandbox file delete is not supported")

    async def _request(
        self,
        method: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        content: bytes | None = None,
        stream: bool = False,
    ) -> Any:
        endpoint = "file-content" if stream else "files"
        url = f"{self._base}/sandbox/{endpoint}"
        headers = {"Authorization": f"Bearer {self._auth_secret}"}
        if content is not None:
            headers["Content-Type"] = "application/octet-stream"
        if self._http_client is not None:
            return await self._http_client.request(
                method, url, json=json, params=params, content=content, headers=headers
            )
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.request(
                method, url, json=json, params=params, content=content, headers=headers
            )
