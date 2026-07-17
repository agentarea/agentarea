"""Shell tool that routes commands to a sandboxed bash executor.

The agent sees a single ``bash(command)`` method. Where the command actually
runs — a dev sandbox container, a K8s warm pool pod, a future microVM — is
hidden behind ``mcp_manager_url``. The toolset talks to the sandbox control
plane and waits for the data-plane runner to complete the execution.

Per-task state isolation is handled by an injected
:class:`ToolInvocationContext`: the activity layer constructs it from the
Temporal task's identity (``activity.info().workflow_id``) and hands it to
the toolset at construction time. The toolset reads ``ctx.workflow_id`` to
scope the sandbox call. Without a ctx (standalone SDK use, unit tests),
calls fall through to the stateless sandbox path. The toolset has no
knowledge of Temporal — it just consumes a value object.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from pathlib import PurePosixPath
from typing import Any

import httpx

from .decorator_tool import Toolset, tool_method
from .invocation_context import ToolInvocationContext, empty_context
from .tool_definition import toolset

logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 120
MAX_TIMEOUT_SECONDS = 1800
MAX_INPUT_FILES = 20
MAX_INPUT_FILE_BYTES = 10 * 1024 * 1024
MAX_INPUT_TOTAL_BYTES = 25 * 1024 * 1024


@toolset(
    namespace="agentarea/shell",
    display_name="Shell",
    description="Run bash commands in an isolated sandbox.",
    category="utility",
    requires_user_confirmation=True,
)
class ShellToolset(Toolset):
    """Single-method toolset wrapping sandbox execution control-plane APIs."""

    def __init__(
        self,
        mcp_manager_url: str | None = None,
        ctx: ToolInvocationContext | None = None,
        storage: Any = None,
        workspace_id: str | None = None,
        base_prefix: str = "",
        http_client: Any = None,
    ) -> None:
        super().__init__()
        self._mcp_manager_url = (mcp_manager_url or "").rstrip("/")
        self._ctx = ctx or empty_context()
        self._storage = storage
        self._workspace_id = workspace_id or self._ctx.workspace_id
        self._base_prefix = base_prefix.strip("/")
        self._http_client = http_client

    @tool_method
    async def bash(
        self,
        command: str,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        artifact_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run a bash command and return stdout, stderr, exit code, and requested artifacts."""
        if not self._mcp_manager_url:
            return _tool_error("shell tool is not configured (mcp_manager_url missing)")
        if not isinstance(command, str) or not command.strip():
            return _tool_error("command must be a non-empty string")
        if timeout_seconds <= 0 or timeout_seconds > MAX_TIMEOUT_SECONDS:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        requested_artifacts = _normalize_artifact_paths(artifact_paths)

        command_payload: dict[str, Any] = {
            "script_name": "cmd.sh",
            "script_content": command,
            "timeout_seconds": timeout_seconds,
        }
        if requested_artifacts:
            command_payload["artifact_paths"] = requested_artifacts
        if self._ctx.workflow_id:
            command_payload["workflow_id"] = self._ctx.workflow_id
        input_files = await self._collect_project_input_files()
        if input_files:
            command_payload["input_files"] = input_files
            command_payload["env"] = {"AGENTAREA_INPUT_DIR": "inputs"}

        payload: dict[str, Any] = {
            "workflow_id": self._ctx.workflow_id,
            "workspace_id": self._workspace_id,
            "runtime": {"provider": "agentarea-k8s"},
            "command": command_payload,
        }
        payload = {key: value for key, value in payload.items() if value}

        url = f"{self._mcp_manager_url}/sandbox/executions"
        try:
            client = self._http_client
            owned = False
            if client is None:
                client = httpx.AsyncClient(timeout=30)
                owned = True
            try:
                resp = await client.post(url, json=payload)
                data = await self._wait_for_execution_result(
                    client=client,
                    created=resp,
                    timeout_seconds=timeout_seconds,
                )
            finally:
                if owned:
                    await client.aclose()
        except httpx.HTTPError as exc:
            logger.exception("bash request to %s failed", url)
            return _tool_error(f"failed to reach sandbox: {exc}")
        except SandboxHTTPError as exc:
            return _tool_error(str(exc))

        if not requested_artifacts and not data.get("artifacts"):
            return _shell_outcome(data)

        return await self._format_result_with_artifacts(data)

    async def _wait_for_execution_result(
        self,
        client: Any,
        created: Any,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        return await wait_for_sandbox_execution(
            client=client,
            created=created,
            mcp_manager_url=self._mcp_manager_url,
            timeout_seconds=timeout_seconds,
        )

    async def _collect_project_input_files(self) -> list[dict[str, Any]]:
        project_id = (self._ctx.metadata or {}).get("project_id")
        if not project_id or self._storage is None or not self._workspace_id:
            return []

        prefix = f"projects/{project_id}/"
        try:
            objects = await self._storage.list(self._workspace_id, prefix=prefix)
        except Exception:
            logger.exception("failed to list project input files for %s", project_id)
            return []

        input_files: list[dict[str, Any]] = []
        total = 0
        for obj in objects:
            source_path = str(getattr(obj, "path", ""))
            if not source_path.startswith(prefix):
                continue
            rel = source_path[len(prefix) :].strip("/")
            if not rel or ".." in rel.split("/"):
                continue

            size = int(getattr(obj, "size", 0) or 0)
            if size > MAX_INPUT_FILE_BYTES or total + size > MAX_INPUT_TOTAL_BYTES:
                continue

            try:
                data, content_type = await self._storage.get(self._workspace_id, source_path)
            except Exception:
                logger.exception("failed to load project input file %s", source_path)
                continue

            total += len(data)
            input_files.append(
                {
                    "path": f"inputs/{rel}",
                    "content_base64": base64.b64encode(data).decode("ascii"),
                    "content_type": content_type,
                }
            )
            if len(input_files) >= MAX_INPUT_FILES:
                break

        return input_files

    async def _format_result_with_artifacts(self, data: dict[str, Any]) -> dict[str, Any]:
        artifact_refs: list[dict[str, Any]] = []
        for artifact in data.get("artifacts") or []:
            if not isinstance(artifact, dict):
                continue
            requested_path = str(artifact.get("path") or "")
            entry: dict[str, Any] = {
                "requested_path": requested_path,
                "size": artifact.get("size") or 0,
                "content_type": artifact.get("content_type"),
            }
            if artifact.get("error"):
                entry["error"] = artifact.get("error")
                artifact_refs.append(entry)
                continue

            content_b64 = artifact.get("content_base64") or ""
            if not content_b64:
                entry["error"] = "sandbox returned an empty artifact payload"
                artifact_refs.append(entry)
                continue
            if self._storage is None or not self._workspace_id:
                entry["error"] = "artifact storage is not configured for shell tool"
                artifact_refs.append(entry)
                continue

            try:
                data_bytes = base64.b64decode(content_b64)
                artifact_path = self._artifact_path(requested_path)
                stored = await self._storage.put(
                    self._workspace_id,
                    artifact_path,
                    data_bytes,
                    artifact.get("content_type"),
                )
                entry.update(
                    {
                        "artifact_path": stored.path,
                        "size": stored.size,
                        "content_type": stored.content_type,
                    }
                )
            except Exception as exc:
                entry["error"] = f"failed to store artifact: {exc}"
            artifact_refs.append(entry)

        # The artifact branch reports the same structured outcome as the plain
        # one: an exit code that only exists when no files were requested is
        # exactly the kind of gap that let a failed command look green.
        outcome = _shell_outcome(data, artifacts=artifact_refs)
        outcome["result"] = json.dumps(
            {
                "exit_code": outcome["exit_code"],
                "execution_time_ms": data.get("execution_time_ms", 0),
                "output": _format_result(data),
                "artifacts": artifact_refs,
            },
            ensure_ascii=False,
            indent=2,
        )
        return outcome

    def _artifact_path(self, requested_path: str) -> str:
        clean = PurePosixPath(requested_path.replace("\\", "/")).name
        if not clean:
            clean = "artifact.bin"
        if self._base_prefix:
            return f"{self._base_prefix}/sandbox/{clean}"
        return f"sandbox/{clean}"


async def wait_for_sandbox_execution(
    client: Any,
    created: Any,
    mcp_manager_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Wait for a scheduled sandbox execution to finish; return its result.

    ``POST /sandbox/executions`` only *creates* a pending record — the data-plane
    runner owns the actual work. Any caller that treats the create response as
    completion reports success before anything has run, and never learns that it
    failed. Shared so there is one place that knows this, rather than one per
    caller.
    """
    if created.status_code >= 400:
        raise SandboxHTTPError(f"sandbox returned HTTP {created.status_code}: {created.text}")
    try:
        record = created.json()
    except ValueError as exc:
        raise SandboxHTTPError(f"invalid sandbox response: {created.text}") from exc

    if not isinstance(record, dict):
        raise SandboxHTTPError(f"invalid sandbox response: {created.text}")

    # Unit tests and older MCP Manager versions may return the execution
    # result directly. Treat that as already completed.
    if "id" not in record:
        return record

    deadline = time.monotonic() + timeout_seconds + 60
    while True:
        status = record.get("status")
        if status == "completed":
            result = record.get("result")
            if isinstance(result, dict):
                return result
            return record
        if status in {"failed", "cancelled"}:
            message = record.get("error") or status
            raise SandboxHTTPError(f"sandbox execution {status}: {message}")

        if time.monotonic() >= deadline:
            raise SandboxHTTPError(
                f"sandbox execution timed out waiting for completion: {record.get('id')}"
            )

        await asyncio.sleep(2)
        resp = await client.get(f"{mcp_manager_url}/sandbox/executions/{record['id']}")
        if resp.status_code >= 400:
            raise SandboxHTTPError(f"sandbox status returned HTTP {resp.status_code}: {resp.text}")
        try:
            record = resp.json()
        except ValueError as exc:
            raise SandboxHTTPError(f"invalid sandbox status response: {resp.text}") from exc


def _tool_error(message: str) -> dict[str, Any]:
    """The tool could not run at all — distinct from a command that ran and failed."""
    return {"success": False, "result": f"Error: {message}", "error": message, "outcome": "error"}


def _shell_outcome(
    data: dict[str, Any], artifacts: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Shape a sandbox execution into a structured tool outcome.

    The exit code is data, not prose: every agent runtime worth copying —
    OpenAI's shell tool, Gemini's, Claude Code's — surfaces it as its own field
    rather than a line inside the output. Burying it meant no consumer could see
    that a command had failed, so a red command rendered green and the
    failed-tool metric could only ever read zero.

    ``success`` is derived from it, matching MCP's isError ("the tool ran and
    the operation failed") and Anthropic's bash guidance. It stays a heuristic —
    grep exits 1 on no-match — but the exit code travels alongside, so a
    consumer that knows better can override it. That is the point of carrying
    both.
    """
    exit_code = int(data.get("exit_code", 0) or 0)
    outcome: dict[str, Any] = {
        "success": exit_code == 0,
        "result": _format_result(data),
        "exit_code": exit_code,
        "outcome": "exit",
    }
    paths = [
        str(a.get("artifact_path"))
        for a in (artifacts or [])
        if isinstance(a, dict) and a.get("artifact_path")
    ]
    if paths:
        outcome["artifact_paths"] = paths
    if artifacts:
        outcome["artifacts"] = artifacts
    return outcome


def _normalize_artifact_paths(paths: list[str] | None) -> list[str]:
    if not paths:
        return []
    normalized: list[str] = []
    for path in paths:
        if not isinstance(path, str):
            continue
        clean = path.strip()
        if clean:
            normalized.append(clean)
    return normalized


def _format_result(data: dict[str, Any]) -> str:
    exit_code = data.get("exit_code", 0)
    stdout = (data.get("stdout") or "").rstrip("\n")
    stderr = (data.get("stderr") or "").rstrip("\n")

    if exit_code == 0 and not stderr:
        return stdout if stdout else "(command produced no output)"

    parts = [f"exit_code: {exit_code}"]
    if stdout:
        parts.append(f"stdout:\n{stdout}")
    if stderr:
        parts.append(f"stderr:\n{stderr}")
    return "\n".join(parts)


class SandboxHTTPError(Exception):
    pass
