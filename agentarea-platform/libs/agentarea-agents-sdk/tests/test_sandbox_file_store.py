from __future__ import annotations

import hashlib

import pytest

from agentarea_agents_sdk.tools.file_toolset import FileToolset
from agentarea_agents_sdk.tools.sandbox_file_store import SandboxFileStore


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.content = content
        self.headers = {"content-type": "application/octet-stream"}

    @property
    def text(self) -> str:
        return str(self._payload)

    def json(self) -> dict:
        return self._payload


class _FakeControlPlane:
    """In-memory stand-in for mcp-manager /sandbox/files proxying the executor."""

    def __init__(self) -> None:
        self.files: dict[tuple[str, str, str], bytes] = {}
        self.requests: list[tuple[str, str]] = []
        self.put_params: list[dict] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        content: bytes | None = None,
        headers: dict | None = None,
    ):
        assert headers is not None
        assert headers["Authorization"] == "Bearer file-secret"
        self.requests.append((method, url))
        if method == "PUT" and url.endswith("/sandbox/file-content"):
            assert params is not None and content is not None
            self.put_params.append(params)
            assert params["size"] == len(content)
            assert params["sha256"] == hashlib.sha256(content).hexdigest()
            key = (params["workspace_id"], params["task_id"], params["path"])
            self.files[key] = content
            return _FakeResponse(200, {"path": params["path"], "size": len(content)})
        if method == "GET":
            assert params is not None
            workspace_id = params["workspace_id"]
            task_id = params["task_id"]
            if url.endswith("/sandbox/files") and "list" in params:
                prefix = params["list"]
                paths = [
                    path
                    for (ws, task, path) in self.files
                    if ws == workspace_id and task == task_id and path.startswith(prefix)
                ]
                return _FakeResponse(200, {"paths": sorted(paths)})
            key = (workspace_id, task_id, params["path"])
            if key not in self.files:
                return _FakeResponse(404, {"error": "not_found"})
            data = self.files[key]
            if not url.endswith("/sandbox/file-content"):
                raise AssertionError(f"unexpected url: {url}")
            return _FakeResponse(200, content=data)
        raise AssertionError(f"unexpected method: {method}")


def _store(client: _FakeControlPlane) -> SandboxFileStore:
    return SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        auth_secret="file-secret",
        http_client=client,
    )


@pytest.mark.asyncio
async def test_sandbox_file_store_put_get_round_trip():
    client = _FakeControlPlane()
    store = _store(client)

    result = await store.put("ws", "src/a.py", b"print('ok')", "text/plain")
    assert result.path == "src/a.py"
    assert result.size == len(b"print('ok')")

    data, _ = await store.get("ws", "src/a.py")
    assert data == b"print('ok')"
    assert await store.exists("ws", "src/a.py") is True
    assert await store.exists("ws", "missing.py") is False


@pytest.mark.asyncio
async def test_sandbox_file_store_put_carries_only_file_and_task_metadata():
    client = _FakeControlPlane()
    store = _store(client)

    await store.put("ws", "src/a.py", b"print('ok')", "text/plain")

    assert client.put_params == [
        {
            "workspace_id": "ws",
            "task_id": "task",
            "path": "src/a.py",
            "size": len(b"print('ok')"),
            "sha256": hashlib.sha256(b"print('ok')").hexdigest(),
            "mode": "600",
        }
    ]


@pytest.mark.asyncio
async def test_sandbox_file_store_get_missing_raises_file_not_found():
    store = _store(_FakeControlPlane())
    with pytest.raises(FileNotFoundError):
        await store.get("ws", "nope.txt")


@pytest.mark.asyncio
async def test_sandbox_file_store_rejects_workspace_override():
    store = _store(_FakeControlPlane())
    with pytest.raises(ValueError, match="bound to a different workspace"):
        await store.put("other-workspace", "nope.txt", b"secret")


@pytest.mark.asyncio
async def test_sandbox_file_store_list_returns_written_paths():
    client = _FakeControlPlane()
    store = _store(client)
    await store.put("ws", "a.txt", b"1")
    await store.put("ws", "reports/b.txt", b"2")

    objects = await store.list("ws")
    assert sorted(o.path for o in objects) == ["a.txt", "reports/b.txt"]


@pytest.mark.asyncio
async def test_file_toolset_over_sandbox_store_round_trips_and_lists():
    """The file tool must read back exactly what it wrote through the sandbox store."""
    client = _FakeControlPlane()
    store = _store(client)
    tool = FileToolset(storage=store, workspace_id="ws")

    assert await tool.save_file("hello", "notes/todo.txt") == "notes/todo.txt"
    assert await tool.read_file("notes/todo.txt") == "hello"

    import json

    listed = json.loads(await tool.list_files())
    assert listed["files"] == ["notes/todo.txt"]


class _Unavailable503:
    """A failed manager call must never fall back to a second Python store."""

    async def request(self, method, url, *, json=None, params=None, content=None, headers=None):
        return _FakeResponse(503, {"error": "sandbox files unavailable"})


@pytest.mark.asyncio
async def test_put_fails_loudly_on_manager_503():
    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        auth_secret="file-secret",
        http_client=_Unavailable503(),
    )
    with pytest.raises(RuntimeError, match="HTTP 503"):
        await store.put("ws", "outputs/a.txt", b"hi", "text/plain")


def test_sandbox_file_store_requires_configuration():
    with pytest.raises(ValueError):
        SandboxFileStore(
            mcp_manager_url="",
            workspace_id="ws",
            task_id="task",
            auth_secret="file-secret",
        )
    with pytest.raises(ValueError):
        SandboxFileStore(
            mcp_manager_url="http://x",
            workspace_id="ws",
            task_id="",
            auth_secret="file-secret",
        )
    with pytest.raises(ValueError):
        SandboxFileStore(
            mcp_manager_url="http://x",
            workspace_id="ws",
            task_id="task",
            auth_secret="",
        )
