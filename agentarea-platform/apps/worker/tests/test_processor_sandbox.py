"""The sandbox runner of processors: one signed execution per event, in the processor's session."""

import json

import httpx
import pytest
from agentarea_streams.domain.errors import ProcessorRuntimeUnavailableError
from agentarea_worker.processor_sandbox import SandboxCodeRunner

SECRET = "s" * 40
WS = "ws-1"
SESSION = "processor-abc"


class _Files:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.reads: list[tuple[str, str, str]] = []

    async def get_object_ref(self, workspace_id, task_id, reference):
        if self.fail:
            raise OSError("object store unreachable")
        self.reads.append((workspace_id, task_id, reference["relative_path"]))
        return reference["content"].encode(), None


def _ref(stream: str, content: str) -> dict:
    return {"relative_path": f".agentarea/executions/x/{stream}.txt", "content": content}


def _runner(handler, files=None, **kwargs) -> SandboxCodeRunner:
    return SandboxCodeRunner(
        manager_url="http://mcp-manager",
        control_secret=SECRET,
        files=files or _Files(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        poll_interval_s=0.001,
        **kwargs,
    )


async def _run(runner: SandboxCodeRunner):
    return await runner.run(
        workspace_id=WS,
        session=SESSION,
        command="python3 - <<'X'\nprint(1)\nX\n",
        timeout_seconds=10,
        max_output_bytes=1000,
    )


def _completed(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"id": "sexec-1", "status": "completed", "result": result})


async def test_a_run_is_one_execution_in_the_processor_session_read_back_from_its_files():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(
                202,
                json={
                    "id": "sexec-1",
                    "status": "queued",
                    "queue_expires_at": "2999-01-01T00:00:00Z",
                },
            )
        return _completed(
            {
                "exit_code": 0,
                "stdout_ref": _ref("stdout", '{"ok": true, "outputs": []}'),
                "stderr_ref": _ref("stderr", "printed"),
            }
        )

    files = _Files()
    run = await _run(_runner(handler, files))

    assert (run.exit_code, run.stdout, run.stdout_truncated, run.stderr) == (
        0,
        '{"ok": true, "outputs": []}',
        False,
        "",
    )
    created = json.loads(seen[0].content)
    assert created == {
        "workspace_id": WS,
        "task_id": SESSION,
        "command": {
            "command_body": "python3 - <<'X'\nprint(1)\nX\n",
            "timeout_seconds": 10,
            "stdout_max_bytes": 1000,
            "stderr_max_bytes": 4096,
        },
    }
    assert seen[0].headers["X-Agentarea-Task-ID"] == SESSION
    assert seen[0].headers["Authorization"].startswith("Bearer ")
    assert [r.method for r in seen] == ["POST", "GET"]
    assert files.reads == [(WS, SESSION, ".agentarea/executions/x/stdout.txt")]


async def test_a_failed_run_also_reads_stderr_and_reports_truncation():
    def handler(request: httpx.Request) -> httpx.Response:
        return _completed(
            {
                "exit_code": 137,
                "stdout_truncated": True,
                "stdout_ref": _ref("stdout", ""),
                "stderr_ref": _ref("stderr", "Killed"),
            }
        )

    run = await _run(_runner(handler))
    assert (run.exit_code, run.stdout_truncated, run.stderr) == (137, True, "Killed")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503, json={"error": "sandbox_control_unavailable"}),
        httpx.Response(200, json={"id": "sexec-1", "status": "failed", "error": "no runner"}),
    ],
)
async def test_a_sandbox_that_cannot_run_the_code_is_unavailable(response):
    with pytest.raises(ProcessorRuntimeUnavailableError):
        await _run(_runner(lambda request: response))


async def test_an_unreachable_sandbox_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ProcessorRuntimeUnavailableError, match="refused"):
        await _run(_runner(handler))


async def test_output_that_cannot_be_read_back_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return _completed({"exit_code": 0, "stdout_ref": _ref("stdout", "{}")})

    with pytest.raises(ProcessorRuntimeUnavailableError, match="object store"):
        await _run(_runner(handler, _Files(fail=True)))


async def test_a_run_that_never_finishes_is_unavailable_past_its_deadline():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            return httpx.Response(200, json={"id": "sexec-1", "status": "cancelled"})
        return httpx.Response(
            200,
            json={
                "id": "sexec-1",
                "status": "running",
                "execution_expires_at": "2999-01-01T00:00:00Z",
            },
        )

    with pytest.raises(ProcessorRuntimeUnavailableError, match="did not answer"):
        await _run(_runner(handler, grace_s=-9.9))


def test_the_runner_refuses_to_build_without_its_configuration():
    with pytest.raises(ValueError, match="AGENTAREA_MCP_MANAGER_URL"):
        SandboxCodeRunner(manager_url="", control_secret=SECRET, files=_Files())
    with pytest.raises(ValueError, match="AGENTAREA_SANDBOX_CONTROL_SECRET"):
        SandboxCodeRunner(manager_url="http://m", control_secret="short", files=_Files())
