"""Unit tests for the ShellToolset HTTP wrapper.

The toolset is a thin client over POST /sandbox/executions on mcp-manager.
These tests pin the contract (payload shape + ToolInvocationContext
propagation + response formatting) without spinning up the sandbox
itself — that's covered by the Go-side activation-service tests and the
e2e harness.
"""

from __future__ import annotations

import hashlib
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
    """Captures scheduling and returns a record-shaped completion poll."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[str] = []

    async def post(self, url: str, json: dict[str, Any]) -> _FakeResponse:  # noqa: A002
        self.calls.append((url, json))
        if self.response.status_code >= 400:
            return self.response
        return _FakeResponse(
            status_code=202,
            payload={"id": "sexec-test", "status": "queued"},
        )

    async def get(self, url: str) -> _FakeResponse:
        self.get_calls.append(url)
        return _FakeResponse(
            payload={
                "id": "sexec-test",
                "status": "completed",
                "result": self.response.json(),
            },
        )

    async def aclose(self) -> None:  # client is borrowed, this is a no-op
        pass


class _WorkspaceRepository:
    def __init__(self, workspace_id: str = "workspace-test", task_id: str = "task-w") -> None:
        self.workspace_id = workspace_id
        self.task_id = task_id
        self.imports: list[dict[str, Any]] = []
        self.files: dict[str, bytes] = {}

    async def put(
        self,
        workspace_id: str,
        task_id: str,
        path: str,
        data: bytes,
        content_type: str | None = None,
        **_: Any,
    ) -> Any:
        assert workspace_id
        assert task_id
        assert content_type == "text/x-shellscript"
        self.files[path] = data
        return self._object(path)

    async def get(self, workspace_id: str, task_id: str, path: str):
        assert workspace_id
        assert task_id
        return self.files[path], "text/plain"

    async def get_object_ref(self, workspace_id: str, task_id: str, reference: dict[str, Any]):
        assert workspace_id == self.workspace_id
        assert task_id == self.task_id
        path = reference["relative_path"]
        item = self._object(path)
        if (
            reference.get("object_uri") != item.object_uri
            or reference.get("sha256") != item.sha256
            or reference.get("size") != item.size
            or not reference.get("object_version_or_etag")
        ):
            raise ValueError("tampered object reference")
        return self.files[path], item.content_type

    async def list(self, workspace_id: str, task_id: str):
        assert workspace_id
        assert task_id
        return [self._object(path) for path in sorted(self.files)]

    def add_output(self, path: str, data: bytes) -> dict[str, Any]:
        self.files[path] = data
        item = self._object(path)
        return {
            "relative_path": item.path,
            "object_uri": item.object_uri,
            "object_version_or_etag": "etag-test",
            "sha256": item.sha256,
            "size": item.size,
            "content_type": item.content_type,
        }

    def _object(self, path: str) -> Any:
        data = self.files[path]
        return type(
            "WorkspaceObject",
            (),
            {
                "path": path,
                "size": len(data),
                "content_type": "text/plain",
                "sha256": hashlib.sha256(data).hexdigest(),
                "object_uri": (
                    f"s3://artifacts/workspaces/{self.workspace_id}/tasks/{self.task_id}/objects/"
                    f"{hashlib.sha256(data).hexdigest()}"
                ),
                "generation": 4,
            },
        )()

    async def import_workspace_prefix(self, workspace_id: str, task_id: str, **kwargs: Any):
        self.imports.append({"workspace_id": workspace_id, "task_id": task_id, **kwargs})


def _refs_result(
    repository: _WorkspaceRepository,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int = 0,
) -> dict[str, Any]:
    return {
        "stdout_ref": repository.add_output(
            ".agentarea/executions/execution-test/stdout.txt", stdout
        ),
        "stderr_ref": repository.add_output(
            ".agentarea/executions/execution-test/stderr.txt", stderr
        ),
        "exit_code": exit_code,
    }


def _ctx(
    workflow_id: str,
    metadata: dict[str, str] | None = None,
    *,
    task_id: str = "",
    workspace_id: str = "",
) -> ToolInvocationContext:
    task_id = task_id or f"task-{workflow_id}"
    workspace_id = workspace_id or "workspace-test"
    return ToolInvocationContext(
        workflow_id=workflow_id,
        task_id=task_id,
        workspace_id=workspace_id,
        metadata=metadata or {},
    )


@pytest.mark.asyncio
async def test_bash_propagates_workflow_id_from_ctx():
    repository = _WorkspaceRepository("workspace-1", "task-abc")
    fake = _RecordingClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx("workflow-abc", task_id="task-abc", workspace_id="workspace-1"),
        workspace_repository=repository,
        http_client=fake,
    )
    result = await tool.bash("echo ok")

    assert result["result"] == "ok"
    assert len(fake.calls) == 1
    url, payload = fake.calls[0]
    assert url == "http://mcp-manager:8000/sandbox/executions"
    assert payload["command"]["command_body"] == "echo ok"
    assert "command_path" not in payload["command"]
    assert "script_name" not in payload["command"]
    assert "script_content" not in payload["command"]
    assert payload["workflow_id"] == "workflow-abc"
    assert payload["task_id"] == "task-abc"
    assert payload["workspace_id"] == "workspace-1"
    assert payload["runtime"]["package_install"] == "allowed"
    assert payload["command"]["workflow_id"] == "workflow-abc"
    assert payload["command"]["timeout_seconds"] == 120
    assert "workspace_manifest_ref" not in payload
    assert "env" not in payload["command"]
    assert "args" not in payload["command"]
    assert fake.get_calls == ["http://mcp-manager:8000/sandbox/executions/sexec-test"]
    wire = json.dumps(payload)
    assert "content_base64" not in wire
    assert "input_files" not in wire


@pytest.mark.asyncio
async def test_bash_propagates_locked_package_profile():
    repository = _WorkspaceRepository("workspace-1", "task-abc")
    fake = _RecordingClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx(
            "workflow-abc",
            {"package_install": "locked"},
            task_id="task-abc",
            workspace_id="workspace-1",
        ),
        workspace_repository=repository,
        http_client=fake,
    )

    await tool.bash("echo ok")

    assert fake.calls[0][1]["runtime"]["package_install"] == "locked"


@pytest.mark.asyncio
async def test_bash_rejects_inline_output_transport():
    """stdout/stderr must return as object refs, never inline on the wire."""
    repository = _WorkspaceRepository("workspace-1", "task-1")
    fake = _RecordingClient(_FakeResponse(payload={"stdout": "hi", "stderr": "", "exit_code": 0}))
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w", task_id="task-1", workspace_id="workspace-1"),
        workspace_repository=repository,
        http_client=fake,
    )
    result = await tool.bash("echo hi")

    assert result["success"] is False
    assert "output references" in result["result"]


@pytest.mark.asyncio
async def test_bash_stages_project_inputs_and_sends_command_inline():
    repository = _WorkspaceRepository("workspace-1", "task-1")
    fake = _RecordingClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx(
            "w",
            {"project_id": "project-1"},
            task_id="task-1",
            workspace_id="workspace-1",
        ),
        workspace_repository=repository,
        http_client=fake,
    )
    await tool.bash("find inputs -type f")

    _, payload = fake.calls[0]
    assert "env" not in payload["command"]
    assert repository.imports == [
        {
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "source_prefix": "projects/project-1",
            "target_prefix": "inputs/project",
            "provenance": {"source": "project", "project_id": "project-1"},
        }
    ]
    assert payload["command"]["command_body"] == "find inputs -type f"
    assert "command_path" not in payload["command"]
    assert "workspace_manifest_ref" not in payload
    assert "input_files" not in payload["command"]


@pytest.mark.asyncio
async def test_bash_returns_stdout_only_on_success():
    repository = _WorkspaceRepository()
    fake = _RecordingClient(_FakeResponse(payload=_refs_result(repository, stdout=b"hello\n")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )
    result = await tool.bash("echo hello")
    assert result["result"] == "hello"
    assert result["exit_code"] == 0
    assert result["success"] is True


@pytest.mark.asyncio
async def test_bash_includes_stderr_and_exit_code_on_failure():
    repository = _WorkspaceRepository()
    fake = _RecordingClient(
        _FakeResponse(
            payload=_refs_result(repository, stdout=b"partial", stderr=b"boom", exit_code=2)
        )
    )
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )
    result = await tool.bash("false")

    assert "exit_code: 2" in result["result"]
    assert "partial" in result["result"]
    assert "boom" in result["result"]
    assert result["exit_code"] == 2
    assert result["success"] is False


@pytest.mark.asyncio
async def test_bash_rejects_output_ref_that_does_not_match_committed_identity():
    repository = _WorkspaceRepository()
    payload = _refs_result(repository, stdout=b"trusted")
    payload["stdout_ref"]["sha256"] = "f" * 64
    fake = _RecordingClient(_FakeResponse(payload=payload))
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("echo trusted")

    assert result["success"] is False
    assert "invalid output references" in result["result"]
    assert "trusted" not in result["result"]


@pytest.mark.asyncio
async def test_bash_handles_empty_command():
    fake = _RecordingClient(_FakeResponse(payload={}))
    tool = ShellToolset(mcp_manager_url="http://mcp:8000", ctx=_ctx("w"), http_client=fake)
    result = await tool.bash("   ")
    assert result["success"] is False
    assert result["result"].startswith("Error:")
    assert fake.calls == []


@pytest.mark.asyncio
async def test_bash_returns_error_when_unconfigured():
    tool = ShellToolset()  # no mcp_manager_url, no ctx
    result = await tool.bash("echo x")
    assert result["success"] is False
    assert result["result"].startswith("Error:")


@pytest.mark.asyncio
async def test_bash_surfaces_http_error():
    fake = _RecordingClient(_FakeResponse(status_code=500, text="boom"))
    repository = _WorkspaceRepository()
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )
    result = await tool.bash("echo x")
    assert "HTTP 500" in result["result"]
    assert result["success"] is False
    assert "workspace_manifest_ref" not in fake.calls[0][1]


@pytest.mark.asyncio
async def test_bash_surfaces_network_error():
    class _Broken:
        async def post(self, *_: Any, **__: Any) -> _FakeResponse:
            raise httpx.ConnectError("name resolution failed")

        async def aclose(self) -> None:
            pass

    repository = _WorkspaceRepository()
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=_Broken(),
    )
    result = await tool.bash("echo x")
    assert "failed to reach sandbox" in result["result"]
    assert result["success"] is False


@pytest.mark.asyncio
async def test_bash_clamps_unsafe_timeout():
    repository = _WorkspaceRepository()
    fake = _RecordingClient(_FakeResponse(payload=_refs_result(repository)))
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )
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

    repository_a = _WorkspaceRepository(task_id="task-task-A")
    repository_b = _WorkspaceRepository(task_id="task-task-B")
    fake_a = _RecordingClient(_FakeResponse(payload=_refs_result(repository_a, stdout=b"a")))
    fake_b = _RecordingClient(_FakeResponse(payload=_refs_result(repository_b, stdout=b"b")))
    tool_a = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("task-A"),
        workspace_repository=repository_a,
        http_client=fake_a,
    )
    tool_b = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("task-B"),
        workspace_repository=repository_b,
        http_client=fake_b,
    )

    await asyncio.gather(tool_a.bash("echo a"), tool_b.bash("echo b"))

    assert fake_a.calls[0][1]["workflow_id"] == "task-A"
    assert fake_b.calls[0][1]["workflow_id"] == "task-B"
    assert fake_a.calls[0][1]["command"]["workflow_id"] == "task-A"
    assert fake_b.calls[0][1]["command"]["workflow_id"] == "task-B"
