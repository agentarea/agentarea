"""Unit tests for the ShellToolset HTTP wrapper.

The toolset is a thin client over POST /sandbox/executions on mcp-manager.
These tests pin the contract (payload shape + ToolInvocationContext
propagation + response formatting) without spinning up the sandbox
itself — that's covered by the Go-side activation-service tests and the
e2e harness.
"""

from __future__ import annotations

import base64
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
        self.content_types: dict[str, str | None] = {}

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
        self.files[path] = data
        self.content_types[path] = content_type
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

    async def list(self, workspace_id: str, task_id: str, prefix: str = "", **_: Any):
        assert workspace_id
        assert task_id
        return [
            self._object(path)
            for path in sorted(self.files)
            if not prefix or path.startswith(prefix)
        ]

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
    assert "provider" not in payload["runtime"]
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


class _CopyOutClient(_RecordingClient):
    """RecordingClient that also serves file reads from a fake sandbox disk."""

    def __init__(
        self, response: _FakeResponse, sandbox_files: dict[str, bytes], read_status: int = 200
    ) -> None:
        super().__init__(response)
        self.sandbox_files = sandbox_files
        self.read_status = read_status
        self.file_reads: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, *, params: dict[str, Any], **_: Any):
        assert method == "GET"
        assert url.endswith("/sandbox/files")
        self.file_reads.append(params)
        if self.read_status >= 400:
            return _FakeResponse(status_code=self.read_status, text="routing unavailable")
        data = self.sandbox_files.get(params["path"])
        if data is None:
            return _FakeResponse(status_code=404, text="not found")
        return _FakeResponse(
            payload={"content_base64": base64.b64encode(data).decode("ascii"), "size": len(data)}
        )


def _result_with_artifact(
    repository: _WorkspaceRepository,
    *,
    path: str,
    size: int,
    content_type: str,
    sha256: str | None = None,
) -> dict[str, Any]:
    result = _refs_result(repository, stdout=b"built it")
    artifact: dict[str, Any] = {"path": path, "size": size, "content_type": content_type}
    if sha256 is not None:
        artifact["sha256"] = sha256
    result["artifacts"] = [artifact]
    return result


_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest.mark.asyncio
async def test_bash_copies_bash_produced_artifact_out_to_durable_store():
    # A binary the agent creates via bash lands only on the ephemeral sandbox
    # disk with NO committed object ref. The tool must copy it out to the durable
    # task workspace before returning, so it survives the pod and /files serves it.
    repository = _WorkspaceRepository()
    body = b"PK\x03\x04 fake xlsx bytes"
    payload = _result_with_artifact(
        repository,
        path="reports/model.xlsx",
        size=len(body),
        content_type=_XLSX,
        sha256=hashlib.sha256(body).hexdigest(),
    )
    fake = _CopyOutClient(_FakeResponse(payload=payload), {"reports/model.xlsx": body})
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python make_xlsx.py", artifact_paths=["reports/model.xlsx"])

    # the deliverable is now durable and retrievable
    assert repository.files["reports/model.xlsx"] == body
    assert repository.content_types["reports/model.xlsx"] == _XLSX
    # it was read from the sandbox's live workspace, scoped to this task
    assert fake.file_reads == [
        {"workspace_id": "workspace-test", "task_id": "task-w", "path": "reports/model.xlsx"}
    ]
    # the returned artifact ref carries a committed object_uri, not an error
    artifacts = json.loads(result["result"])["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["object_uri"]
    assert "error" not in artifacts[0]
    assert result["artifact_paths"] == ["reports/model.xlsx"]


@pytest.mark.asyncio
async def test_bash_refuses_to_persist_artifact_over_size_cap():
    from agentarea_agents_sdk.tools.shell_toolset import MAX_DURABLE_ARTIFACT_BYTES

    repository = _WorkspaceRepository()
    payload = _result_with_artifact(
        repository,
        path="huge.bin",
        size=MAX_DURABLE_ARTIFACT_BYTES + 1,
        content_type="application/octet-stream",
    )
    fake = _CopyOutClient(_FakeResponse(payload=payload), {})
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python make_huge.py", artifact_paths=["huge.bin"])

    # over the cap: never read, never persisted, and the failure is loud
    assert fake.file_reads == []
    assert "huge.bin" not in repository.files
    artifacts = json.loads(result["result"])["artifacts"]
    assert "cap" in artifacts[0]["error"]
    assert "object_uri" not in artifacts[0]


@pytest.mark.asyncio
async def test_bash_surfaces_sandbox_read_failure_instead_of_silent_loss():
    repository = _WorkspaceRepository()
    payload = _result_with_artifact(
        repository, path="reports/model.xlsx", size=10, content_type=_XLSX
    )
    fake = _CopyOutClient(
        _FakeResponse(payload=payload), {"reports/model.xlsx": b"x"}, read_status=503
    )
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python make_xlsx.py", artifact_paths=["reports/model.xlsx"])

    # the read failed (no per-task routing): surfaced as an error, not persisted,
    # never silently reported as delivered
    assert "reports/model.xlsx" not in repository.files
    artifacts = json.loads(result["result"])["artifacts"]
    assert "failed to persist" in artifacts[0]["error"]
    assert "object_uri" not in artifacts[0]


@pytest.mark.asyncio
async def test_bash_refuses_artifact_whose_bytes_changed_after_report():
    # The executor hashed the file it discovered; if the bytes served on read
    # differ (a swap in the live workspace), refuse to commit content the
    # executor never declared instead of silently persisting the swap.
    repository = _WorkspaceRepository()
    served = b"totally different bytes than declared"
    payload = _result_with_artifact(
        repository,
        path="reports/model.xlsx",
        size=len(served),
        content_type=_XLSX,
        sha256=hashlib.sha256(b"the originally reported bytes").hexdigest(),
    )
    fake = _CopyOutClient(_FakeResponse(payload=payload), {"reports/model.xlsx": served})
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python make_xlsx.py", artifact_paths=["reports/model.xlsx"])

    assert "reports/model.xlsx" not in repository.files
    artifacts = json.loads(result["result"])["artifacts"]
    assert "changed between report and read" in artifacts[0]["error"]
    assert "object_uri" not in artifacts[0]


@pytest.mark.asyncio
async def test_bash_caps_on_actual_read_bytes_not_just_declared_size(monkeypatch):
    # The pre-read cap trusts the executor-declared size; a misreported small size
    # must not let oversized ACTUAL bytes get buffered and committed.
    import agentarea_agents_sdk.tools.shell_toolset as st

    monkeypatch.setattr(st, "MAX_DURABLE_ARTIFACT_BYTES", 8)
    repository = _WorkspaceRepository()
    served = b"far more than eight bytes on the wire"
    payload = _result_with_artifact(
        repository, path="big.bin", size=3, content_type="application/octet-stream"
    )
    fake = _CopyOutClient(_FakeResponse(payload=payload), {"big.bin": served})
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python make_big.py", artifact_paths=["big.bin"])

    assert "big.bin" not in repository.files
    artifacts = json.loads(result["result"])["artifacts"]
    assert "durability cap" in artifacts[0]["error"]
    assert "object_uri" not in artifacts[0]


@pytest.mark.asyncio
async def test_bash_refuses_unsafe_artifact_path_before_reading():
    repository = _WorkspaceRepository()
    payload = _result_with_artifact(
        repository, path="../../etc/passwd", size=6, content_type="text/plain"
    )
    fake = _CopyOutClient(_FakeResponse(payload=payload), {"../../etc/passwd": b"root:x"})
    tool = ShellToolset(
        mcp_manager_url="http://mcp:8000",
        ctx=_ctx("w"),
        workspace_repository=repository,
        http_client=fake,
    )

    result = await tool.bash("python x.py", artifact_paths=["../../etc/passwd"])

    # rejected before the proxy read; nothing persisted
    assert fake.file_reads == []
    assert "../../etc/passwd" not in repository.files
    artifacts = json.loads(result["result"])["artifacts"]
    assert "unsafe artifact path" in artifacts[0]["error"]
    assert "object_uri" not in artifacts[0]


class _CopyInClient(_RecordingClient):
    """RecordingClient that also captures file writes to the fake sandbox disk."""

    def __init__(self, response: _FakeResponse) -> None:
        super().__init__(response)
        self.file_writes: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, *, json: dict[str, Any], **_: Any):
        assert method == "PUT"
        assert url.endswith("/sandbox/files")
        self.file_writes.append(json)
        return _FakeResponse(
            status_code=200, payload={"path": json["path"], "size": len(json["content_base64"])}
        )


@pytest.mark.asyncio
async def test_bash_copies_durable_inputs_into_sandbox():
    # A durable task input (an attachment, an imported project file) must land
    # in the sandbox filesystem before bash runs, so the agent sees one working
    # directory. The tool pushes each input through the /sandbox/files PUT proxy.
    repository = _WorkspaceRepository("workspace-1", "task-abc")
    repository.files["inputs/attachments/data.csv"] = b"a,b\n1,2\n"
    fake = _CopyInClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx("workflow-abc", task_id="task-abc", workspace_id="workspace-1"),
        workspace_repository=repository,
        http_client=fake,
    )

    await tool.bash("cat inputs/attachments/data.csv")

    # the durable input was written into the sandbox FS at the same relative path
    assert len(fake.file_writes) == 1
    write = fake.file_writes[0]
    assert write["workspace_id"] == "workspace-1"
    assert write["task_id"] == "task-abc"
    assert write["package_install"] == "allowed"
    assert write["path"] == "inputs/attachments/data.csv"
    assert base64.b64decode(write["content_base64"]) == b"a,b\n1,2\n"
    # the execution still carries the command; no S3 input_refs on the wire
    _, payload = fake.calls[0]
    assert payload["command"]["command_body"] == "cat inputs/attachments/data.csv"
    assert "input_refs" not in payload["command"]


@pytest.mark.asyncio
async def test_bash_stages_inputs_only_once_per_session():
    # The session workspace persists inputs across bash calls, so the copy-in
    # runs once — a second bash in the same session must not re-push them.
    repository = _WorkspaceRepository("workspace-1", "task-abc")
    repository.files["inputs/attachments/data.csv"] = b"a,b\n1,2\n"
    fake = _CopyInClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx("workflow-abc", task_id="task-abc", workspace_id="workspace-1"),
        workspace_repository=repository,
        http_client=fake,
    )

    await tool.bash("head inputs/attachments/data.csv")
    await tool.bash("wc -l inputs/attachments/data.csv")

    assert len(fake.file_writes) == 1


@pytest.mark.asyncio
async def test_bash_writes_no_inputs_when_none_durable():
    repository = _WorkspaceRepository("workspace-1", "task-abc")
    fake = _CopyInClient(_FakeResponse(payload=_refs_result(repository, stdout=b"ok")))
    tool = ShellToolset(
        mcp_manager_url="http://mcp-manager:8000",
        ctx=_ctx("workflow-abc", task_id="task-abc", workspace_id="workspace-1"),
        workspace_repository=repository,
        http_client=fake,
    )

    await tool.bash("echo ok")

    assert fake.file_writes == []
    _, payload = fake.calls[0]
    assert "input_refs" not in payload["command"]
    assert payload["command"]["command_body"] == "echo ok"
