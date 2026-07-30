"""StorageClient backed by the mcp-manager sandbox file API.

The file tool must write to the same filesystem the shell tool runs bash in.
Routing writes through the object-store task workspace put the agent's files on a
different filesystem than the pod's ``/workspace``, so code the agent saved was
invisible to bash and tasks stalled. This store talks to the control-plane
``/sandbox/files`` endpoint (base URL is ``mcp_manager_url``, exactly as
:class:`ShellToolset` uses), which proxies to the executor operating on the pod
workspace. The control plane signs the sandbox token; no secret lives here.

It implements the ``StorageClient`` protocol consumed by
:class:`agentarea_agents_sdk.tools.file_toolset.FileToolset`.
"""

from __future__ import annotations

import base64
from typing import Any, Literal

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
        package_install: Literal["allowed", "locked"],
        timeout_seconds: float = 30.0,
        http_client: Any = None,
        durable: Any = None,
    ) -> None:
        base = (mcp_manager_url or "").rstrip("/")
        if not base:
            raise ValueError("mcp_manager_url is required for the sandbox file store")
        if not workspace_id:
            raise ValueError("workspace_id is required for the sandbox file store")
        if not task_id:
            raise ValueError("task_id is required for the sandbox file store")
        if package_install not in {"allowed", "locked"}:
            raise ValueError("package_install must be allowed or locked")
        self._base = base
        self._workspace_id = workspace_id
        self._task_id = task_id
        self._package_install = package_install
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        # Optional durable, task-scoped export target (WorkspaceRepository). The
        # pod /workspace is ephemeral and invisible to the user; write-through so
        # files the agent saves land in the durable task workspace the /files API
        # serves. Reads still come from /workspace (bash's live state).
        self._durable = durable

    async def put(
        self,
        workspace_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
    ) -> StoredObject:
        payload = {
            "workspace_id": workspace_id or self._workspace_id,
            "task_id": self._task_id,
            "package_install": self._package_install,
            "path": path,
            "content_base64": base64.b64encode(data).decode("ascii"),
        }
        response = await self._request("PUT", json=payload)
        if response.status_code == 503 and self._durable is not None:
            # The control-plane backend has no per-task file routing (e.g. the
            # K8s warm-pool path until sticky routing lands). Persist to the
            # durable task workspace only — preserving pre-change prod behavior
            # instead of hard-failing the file tool.
            await self._durable.put(
                workspace_id or self._workspace_id, self._task_id, path, data, content_type
            )
            return StoredObject(path=path, size=len(data), content_type=content_type)
        if response.status_code >= 400:
            raise RuntimeError(
                f"sandbox file put failed for {path!r}: HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        # Write-through to the durable, user-visible task workspace. Fail loudly
        # if this leg fails: a deliverable the user cannot reach is a silent loss.
        if self._durable is not None:
            await self._durable.put(
                workspace_id or self._workspace_id,
                self._task_id,
                path,
                data,
                content_type,
            )
        return StoredObject(
            path=str(body.get("path", path)),
            size=int(body.get("size", len(data))),
            content_type=content_type,
        )

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        response = await self._request(
            "GET",
            params={
                "workspace_id": workspace_id or self._workspace_id,
                "task_id": self._task_id,
                "path": path,
            },
        )
        if response.status_code == 503 and self._durable is not None:
            return await self._durable.get(workspace_id or self._workspace_id, self._task_id, path)
        if response.status_code == 404:
            # Not on the sandbox disk yet — e.g. a task input that copy-in only
            # materializes on the first bash run. Fall back to the durable task
            # workspace so the file tool can read inputs regardless of whether a
            # shell command ran first (one coherent view for the agent). Durable
            # raises FileNotFoundError itself when the path genuinely does not exist.
            if self._durable is not None:
                return await self._durable.get(
                    workspace_id or self._workspace_id, self._task_id, path
                )
            raise FileNotFoundError(path)
        if response.status_code >= 400:
            raise RuntimeError(
                f"sandbox file get failed for {path!r}: HTTP {response.status_code}: {response.text}"
            )
        body = response.json()
        return base64.b64decode(body["content_base64"]), None

    async def exists(self, workspace_id: str, path: str) -> bool:
        try:
            await self.get(workspace_id, path)
        except FileNotFoundError:
            return False
        return True

    async def list(self, workspace_id: str, prefix: str = "") -> list[StoredObject]:
        response = await self._request(
            "GET",
            params={
                "workspace_id": workspace_id or self._workspace_id,
                "task_id": self._task_id,
                "list": prefix,
            },
        )
        if response.status_code == 503 and self._durable is not None:
            objects = await self._durable.list(
                workspace_id or self._workspace_id, self._task_id, prefix
            )
            return [
                StoredObject(
                    path=str(getattr(o, "path", "") or ""), size=int(getattr(o, "size", 0) or 0)
                )
                for o in objects
                if getattr(o, "path", None)
            ]
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
    ) -> Any:
        url = f"{self._base}/sandbox/files"
        if self._http_client is not None:
            return await self._http_client.request(method, url, json=json, params=params)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            return await client.request(method, url, json=json, params=params)
