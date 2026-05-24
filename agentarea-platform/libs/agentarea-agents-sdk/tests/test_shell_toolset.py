"""Unit tests for the ShellToolset HTTP wrapper.

The toolset is a thin client over POST /sandbox/executions on mcp-manager.
These tests pin the contract (payload shape + ToolInvocationContext
propagation + response formatting) without spinning up the sandbox
itself — that's covered by the Go-side activation-service tests and the
e2e harness.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from agentarea_agents_sdk.tools.invocation_context import ToolInvocationContext
from agentarea_agents_sdk.tools.shell_toolset import ShellToolset


class _FakeResponse:
    def __init__(
        self, status_code: int = 200, payload: dict[str, Any] | None = None, text: str = ""
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text or json.dumps(payload or {})

    def json(self) -> dict[str, Any]:
        if self._payload is None:
            raise ValueError("no payload")
        return self._payload


class _RecordingClient:
    """Captures the last POST and returns a scripted response."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:  # noqa: A002
        self.calls.append((url, json))
        return self.response

    async def aclose(self) -> None:  # client is borrowed, this is a no-op
        pass


class _Object:
    def __init__(self, path: str, size: int) -> None:
        self.path = path
        self.size = size


class _Storage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    async def list(self, workspace_id: str, prefix: str = "") -> list[_Object]:
        return [
            _Object(path, len(data))
            for path, data in self.objects.items()
            if path.startswith(prefix)
        ]

    async def get(self, workspace_id: str, path: str) -> tuple[bytes, str | None]:
        return self.objects[path], "application/octet-stream"


def _ctx(workflow_id: str, metadata: dict[str, str] | None = None) -> ToolInvocationContext:
    return ToolInvocationContext(workflow_id=workflow_id, metadata=metadata or {})


@pytest.mark.asyncio
async def test_bash_propagates_workflow_id_from_ctx():
    fake = _RecordingClient(_FakeResponse(payload={"stdout": "ok", "stderr": "", "exit_code": 0}))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx("task-abc"),
        http_client=fake,
    )
    result = await tool.bash("echo ok")

    assert result == "ok"
    assert len(fake.calls) == 1
    url, payload = fake.calls[0]
    assert url == "http://mcp-manager:8000/sandbox/executions"
    assert payload["command"]["script_name"] == "cmd.sh"
    assert payload["command"]["script_content"] == "echo ok"
    assert payload["workflow_id"] == "task-abc"
    assert payload["command"]["workflow_id"] == "task-abc"
    assert payload["command"]["timeout_seconds"] == 120


@pytest.mark.asyncio
async def test_bash_omits_workflow_id_without_ctx():
    fake = _RecordingClient(_FakeResponse(payload={"stdout": "hi", "stderr": "", "exit_code": 0}))
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", http_client=fake)
    await tool.bash("echo hi")

    _, payload = fake.calls[0]
    assert "workflow_id" not in payload
    assert "workflow_id" not in payload["command"]


@pytest.mark.asyncio
async def test_bash_mounts_project_files_as_inputs():
    fake = _RecordingClient(_FakeResponse(payload={"stdout": "ok", "stderr": "", "exit_code": 0}))
    storage = _Storage(
        {
            "projects/project-1/source.docx": b"docx bytes",
            "projects/project-1/nested/info.txt": b"hello",
            "projects/other/skip.txt": b"skip",
        }
    )
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w", {"project_id": "project-1"}),
        storage=storage,
        workspace_id="workspace-1",
        http_client=fake,
    )
    await tool.bash("find inputs -type f")

    _, payload = fake.calls[0]
    assert payload["command"]["env"]["AGENTAREA_INPUT_DIR"] == "inputs"
    assert [item["path"] for item in payload["command"]["input_files"]] == [
        "inputs/source.docx",
        "inputs/nested/info.txt",
    ]
    assert payload["command"]["input_files"][0]["content_base64"] == "ZG9jeCBieXRlcw=="


@pytest.mark.asyncio
async def test_bash_returns_stdout_only_on_success():
    fake = _RecordingClient(
        _FakeResponse(payload={"stdout": "hello\n", "stderr": "", "exit_code": 0})
    )
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    result = await tool.bash("echo hello")
    assert result == "hello"


@pytest.mark.asyncio
async def test_bash_includes_stderr_and_exit_code_on_failure():
    fake = _RecordingClient(
        _FakeResponse(payload={"stdout": "partial", "stderr": "boom", "exit_code": 2})
    )
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    result = await tool.bash("false")

    assert "exit_code: 2" in result
    assert "partial" in result
    assert "boom" in result


@pytest.mark.asyncio
async def test_bash_handles_empty_command():
    fake = _RecordingClient(_FakeResponse(payload={}))
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    result = await tool.bash("   ")
    assert result.startswith("Error:")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_bash_returns_error_when_unconfigured():
    tool = ShellToolset()  # no mcp_manager_url, no ctx
    result = await tool.bash("echo x")
    assert result.startswith("Error:")


@pytest.mark.asyncio
async def test_bash_surfaces_http_error():
    fake = _RecordingClient(_FakeResponse(status_code=500, text="boom"))
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    result = await tool.bash("echo x")
    assert "HTTP 500" in result


@pytest.mark.asyncio
async def test_bash_surfaces_network_error():
    class _Broken:
        async def post(self, *_: Any, **__: Any) -> _FakeResponse:
            raise httpx.ConnectError("name resolution failed")

        async def aclose(self) -> None:
            pass

    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=_Broken())
    result = await tool.bash("echo x")
    assert "failed to reach sandbox" in result


@pytest.mark.asyncio
async def test_bash_clamps_unsafe_timeout():
    fake = _RecordingClient(_FakeResponse(payload={"stdout": "", "stderr": "", "exit_code": 0}))
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    await tool.bash("echo x", timeout_seconds=0)
    await tool.bash("echo x", timeout_seconds=1800)
    await tool.bash("echo x", timeout_seconds=10000)

    assert fake.calls[0][1]["command"]["timeout_seconds"] == 120  # 0 → default
    assert fake.calls[1][1]["command"]["timeout_seconds"] == 1800
    assert fake.calls[2][1]["command"]["timeout_seconds"] == 120  # 10000 → default


@pytest.mark.asyncio
async def test_concurrent_bash_calls_keep_independent_ctx():
    """Two ShellToolset instances with different ctx must not bleed into
    each other under asyncio.gather. The whole reason we ditched the
    ContextVar is so this works."""
    import asyncio

    fake_a = _RecordingClient(_FakeResponse(payload={"stdout": "a", "stderr": "", "exit_code": 0}))
    fake_b = _RecordingClient(_FakeResponse(payload={"stdout": "b", "stderr": "", "exit_code": 0}))
    tool_a = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("task-A"), http_client=fake_a)
    tool_b = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("task-B"), http_client=fake_b)

    await asyncio.gather(tool_a.bash("echo a"), tool_b.bash("echo b"))

    assert fake_a.calls[0][1]["workflow_id"] == "task-A"
    assert fake_b.calls[0][1]["workflow_id"] == "task-B"
    assert fake_a.calls[0][1]["command"]["workflow_id"] == "task-A"
    assert fake_b.calls[0][1]["command"]["workflow_id"] == "task-B"
