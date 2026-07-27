from __future__ import annotations

import base64

import pytest

from agentarea_agents_sdk.tools.file_toolset import FileToolset
from agentarea_agents_sdk.tools.sandbox_file_store import SandboxFileStore


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload

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

    async def request(
        self,
        method: str,
        url: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ):
        self.requests.append((method, url))
        if not url.endswith("/sandbox/files"):
            raise AssertionError(f"unexpected url: {url}")
        if method == "PUT":
            assert json is not None
            key = (json["workspace_id"], json["task_id"], json["path"])
            self.files[key] = base64.b64decode(json["content_base64"])
            return _FakeResponse(200, {"path": json["path"], "size": len(self.files[key])})
        if method == "GET":
            assert params is not None
            workspace_id = params["workspace_id"]
            task_id = params["task_id"]
            if "list" in params:
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
            return _FakeResponse(
                200,
                {"content_base64": base64.b64encode(data).decode("ascii"), "size": len(data)},
            )
        raise AssertionError(f"unexpected method: {method}")


def _store(client: _FakeControlPlane) -> SandboxFileStore:
    return SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
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
async def test_sandbox_file_store_get_missing_raises_file_not_found():
    store = _store(_FakeControlPlane())
    with pytest.raises(FileNotFoundError):
        await store.get("ws", "nope.txt")


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


class _FakeDurable:
    """Records write-through puts to the durable, user-visible task workspace."""

    def __init__(self, fail: bool = False) -> None:
        self.puts: list[tuple[str, str, str, bytes, str | None]] = []
        self._fail = fail

    async def put(self, workspace_id, task_id, path, data, content_type=None, **kwargs):
        if self._fail:
            raise RuntimeError("durable store unavailable")
        self.puts.append((workspace_id, task_id, path, data, content_type))


@pytest.mark.asyncio
async def test_put_writes_through_to_durable_task_workspace():
    client = _FakeControlPlane()
    durable = _FakeDurable()
    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=client,
        durable=durable,
    )
    await store.put("ws", "outputs/deck.pptx", b"PPTXDATA", "application/vnd.ms-powerpoint")
    # landed in the sandbox /workspace (bash-visible)
    assert client.files[("ws", "task", "outputs/deck.pptx")] == b"PPTXDATA"
    # AND written through to the durable, user-visible task workspace
    assert durable.puts == [
        ("ws", "task", "outputs/deck.pptx", b"PPTXDATA", "application/vnd.ms-powerpoint")
    ]


@pytest.mark.asyncio
async def test_put_fails_loudly_when_durable_write_fails():
    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=_FakeControlPlane(),
        durable=_FakeDurable(fail=True),
    )
    with pytest.raises(RuntimeError):
        await store.put("ws", "a.txt", b"x")


class _Unavailable503:
    """Control plane that has no per-task file routing (K8s path) — always 503."""

    async def request(self, method, url, *, json=None, params=None):
        return _FakeResponse(503, {"error": "sandbox files unavailable"})


@pytest.mark.asyncio
async def test_put_falls_back_to_durable_on_503():
    durable = _FakeDurable()
    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=_Unavailable503(),
        durable=durable,
    )
    await store.put("ws", "outputs/a.txt", b"hi", "text/plain")
    # persisted to the durable store, not lost
    assert durable.puts == [("ws", "task", "outputs/a.txt", b"hi", "text/plain")]


@pytest.mark.asyncio
async def test_get_falls_back_to_durable_on_503():
    class _DurableWithGet(_FakeDurable):
        async def get(self, workspace_id, task_id, path):
            return b"durable-bytes", "text/plain"

    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=_Unavailable503(),
        durable=_DurableWithGet(),
    )
    data, _ = await store.get("ws", "a.txt")
    assert data == b"durable-bytes"


@pytest.mark.asyncio
async def test_get_falls_back_to_durable_on_404_sandbox_miss():
    """A task input lives in durable storage but is not on the sandbox disk until
    the first bash copy-in. The file tool must still read it (one coherent view),
    so a sandbox 404 falls back to the durable task workspace."""

    class _DurableWithGet(_FakeDurable):
        async def get(self, workspace_id, task_id, path):
            assert (workspace_id, task_id, path) == ("ws", "task", "inputs/attachments/sales.csv")
            return b"product,month,revenue\n", "text/csv"

    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=_FakeControlPlane(),  # returns 404 for the not-yet-copied-in path
        durable=_DurableWithGet(),
    )
    data, _ = await store.get("ws", "inputs/attachments/sales.csv")
    assert data == b"product,month,revenue\n"


@pytest.mark.asyncio
async def test_get_404_with_durable_miss_still_raises_file_not_found():
    class _DurableMiss(_FakeDurable):
        async def get(self, workspace_id, task_id, path):
            raise FileNotFoundError(path)

    store = SandboxFileStore(
        mcp_manager_url="http://mcp-manager:8000",
        workspace_id="ws",
        task_id="task",
        http_client=_FakeControlPlane(),
        durable=_DurableMiss(),
    )
    with pytest.raises(FileNotFoundError):
        await store.get("ws", "genuinely-missing.txt")


def test_sandbox_file_store_requires_configuration():
    with pytest.raises(ValueError):
        SandboxFileStore(mcp_manager_url="", workspace_id="ws", task_id="task")
    with pytest.raises(ValueError):
        SandboxFileStore(mcp_manager_url="http://x", workspace_id="ws", task_id="")
