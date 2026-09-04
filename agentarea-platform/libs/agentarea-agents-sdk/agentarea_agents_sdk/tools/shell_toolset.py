"""Shell tool that routes commands to a sandboxed bash executor.

The agent sees a single ``bash(command)`` method. Where the command actually
runs — a dev sandbox container, a K8s warm pool pod, a future microVM — is
hidden behind ``mcp_manager_url``. The toolset talks to the sandbox control
plane and waits for the data-plane runner to complete the execution.

Per-task state isolation is handled by an injected
:class:`ToolInvocationContext`. The tool sends only workspace/task identity and
the command to the manager; the Go workspace provider resolves and materializes
the current immutable input manifest. The toolset has no knowledge of Temporal
or of the selected sandbox data plane.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

import httpx

from .decorator_tool import Toolset, tool_method
from .invocation_context import ToolInvocationContext
from .sandbox_control_auth import SandboxControlSigner
from .tool_definition import toolset

logger = logging.getLogger(__name__)


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
        workspace_repository: Any = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        auth_secret: str | None = None,
        http_client: Any = None,
    ) -> None:
        super().__init__()
        self._mcp_manager_url = (mcp_manager_url or "").rstrip("/")
        self._ctx = ctx
        self._workspace_repository = workspace_repository
        self._workspace_id = workspace_id or (self._ctx.workspace_id if self._ctx else "")
        self._task_id = task_id or (self._ctx.task_id if self._ctx else "")
        self._auth_secret = auth_secret or ""
        self._http_client = http_client

    @tool_method
    async def bash(
        self,
        command: str,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Run a bash command and return stdout, stderr, and the exit code."""
        if not self._mcp_manager_url:
            return _tool_error("shell tool is not configured (mcp_manager_url missing)")
        if self._ctx is None:
            return _tool_error("shell tool is not configured (execution context missing)")
        if not isinstance(command, str) or not command.strip():
            return _tool_error("command must be a non-empty string")
        if timeout_seconds is not None and timeout_seconds <= 0:
            return _tool_error("timeout_seconds must be positive when supplied")
        command_payload: dict[str, Any] = {}
        if timeout_seconds is not None:
            command_payload["timeout_seconds"] = timeout_seconds
        if self._ctx.workflow_id:
            command_payload["workflow_id"] = self._ctx.workflow_id
        try:
            await self._stage_inputs()
        except Exception as exc:
            logger.exception("failed to stage task workspace inputs")
            return _tool_error(f"failed to prepare workspace: {exc}")
        command_payload["command_body"] = command

        payload: dict[str, Any] = {
            "workflow_id": self._ctx.workflow_id,
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "command": command_payload,
        }
        payload = {key: value for key, value in payload.items() if value}

        try:
            signer = SandboxControlSigner(
                secret=self._auth_secret,
                workspace_id=self._workspace_id,
                task_id=self._task_id,
            )
        except ValueError as exc:
            return _tool_error(f"shell tool is not configured ({exc})")
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()

        url = f"{self._mcp_manager_url}/sandbox/executions"
        try:
            client = self._http_client
            owned = False
            if client is None:
                client = httpx.AsyncClient(timeout=30)
                owned = True
            try:
                headers = signer.headers("execution.create", body=body)
                headers["Content-Type"] = "application/json"
                resp = await client.post(url, content=body, headers=headers)
                data = await self._wait_for_execution_result(
                    client=client,
                    created=resp,
                    signer=signer,
                )
            finally:
                if owned:
                    await client.aclose()
        except httpx.HTTPError as exc:
            logger.exception("bash request to %s failed", url)
            return _tool_error(f"failed to reach sandbox: {exc}")
        except SandboxHTTPError as exc:
            return _tool_error(str(exc))

        try:
            data = await self._resolve_output_refs(data)
        except Exception as exc:
            logger.exception("sandbox returned invalid output references")
            return _tool_error(f"sandbox returned invalid output references: {exc}")

        return _shell_outcome(data)

    async def _wait_for_execution_result(
        self,
        client: Any,
        created: Any,
        signer: SandboxControlSigner,
    ) -> dict[str, Any]:
        return await wait_for_sandbox_execution(
            client=client,
            created=created,
            mcp_manager_url=self._mcp_manager_url,
            signer=signer,
        )

    async def _stage_inputs(self) -> None:
        """Stage optional trusted project inputs into the task workspace.

        The command body itself travels inline in the execution request. Only
        large project inputs, when requested, are migrated directly between the
        trusted repository and object storage — never through Redis.
        """
        if self._ctx is None:
            raise ValueError("execution context is not configured")
        project_id = (self._ctx.metadata or {}).get("project_id")
        if not project_id:
            return
        if self._workspace_repository is None:
            raise ValueError("workspace repository is not configured")
        if not self._workspace_id or not self._task_id:
            raise ValueError("workspace_id and task_id are required")
        if "/" in project_id or project_id in {".", ".."}:
            raise ValueError("project_id is not a safe object prefix segment")
        await self._workspace_repository.import_workspace_prefix(
            self._workspace_id,
            self._task_id,
            source_prefix=f"projects/{project_id}",
            target_prefix="inputs/project",
            provenance={"source": "project", "project_id": project_id},
        )

    async def _resolve_output_refs(self, data: dict[str, Any]) -> dict[str, Any]:
        """Read stdout/stderr through the trusted canonical workspace repository."""
        if "stdout" in data or "stderr" in data:
            raise ValueError("inline stdout/stderr transport is forbidden")
        resolved = dict(data)
        for stream in ("stdout", "stderr"):
            reference = data.get(f"{stream}_ref")
            if not isinstance(reference, dict):
                raise ValueError(f"missing {stream}_ref")
            path = str(reference.get("relative_path") or "")
            expected_prefix = ".agentarea/executions/"
            pure_path = PurePosixPath(path)
            if (
                not path.startswith(expected_prefix)
                or pure_path.is_absolute()
                or ".." in pure_path.parts
                or pure_path.name != f"{stream}.txt"
            ):
                raise ValueError(f"invalid {stream}_ref path")
            content, _ = await self._workspace_repository.get_object_ref(
                self._workspace_id,
                self._task_id,
                reference,
            )
            resolved[stream] = content.decode("utf-8", errors="replace")
        return resolved


async def wait_for_sandbox_execution(
    client: Any,
    created: Any,
    mcp_manager_url: str,
    signer: SandboxControlSigner,
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

    if "id" not in record:
        raise SandboxHTTPError("invalid sandbox response: missing execution id")

    execution_id = str(record["id"])
    terminal = False
    try:
        while True:
            status = record.get("status")
            if status == "completed":
                terminal = True
                result = record.get("result")
                if isinstance(result, dict):
                    return _merge_committed_output_refs(result, record.get("output_refs"))
                return record
            if status in {"failed", "cancelled"}:
                terminal = True
                message = record.get("error") or status
                raise SandboxHTTPError(f"sandbox execution {status}: {message}")

            if status == "queued" and _deadline_reached(record.get("queue_expires_at")):
                record = await _cancel_pending_execution(
                    client, mcp_manager_url, signer, execution_id
                )
                continue
            if status == "running" and not record.get("execution_expires_at"):
                raise SandboxHTTPError(
                    "invalid sandbox status response: running execution has no deadline"
                )

            headers = signer.headers("execution.read", execution_id=execution_id)
            resp = await client.get(
                f"{mcp_manager_url}/sandbox/executions/{execution_id}", headers=headers
            )
            if resp.status_code >= 400:
                raise SandboxHTTPError(
                    f"sandbox status returned HTTP {resp.status_code}: {resp.text}"
                )
            try:
                record = resp.json()
            except ValueError as exc:
                raise SandboxHTTPError(f"invalid sandbox status response: {resp.text}") from exc

            if record.get("status") not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(2)
    finally:
        if not terminal and record.get("status") == "queued":
            try:
                await _cancel_pending_execution(client, mcp_manager_url, signer, execution_id)
            except Exception:
                logger.exception(
                    "failed to cancel abandoned pending sandbox execution %s", execution_id
                )


async def _cancel_pending_execution(
    client: Any,
    mcp_manager_url: str,
    signer: SandboxControlSigner,
    execution_id: str,
) -> dict[str, Any]:
    headers = signer.headers("execution.cancel", execution_id=execution_id)
    response = await client.delete(
        f"{mcp_manager_url}/sandbox/executions/{execution_id}", headers=headers
    )
    if response.status_code == 409:
        headers = signer.headers("execution.read", execution_id=execution_id)
        response = await client.get(
            f"{mcp_manager_url}/sandbox/executions/{execution_id}", headers=headers
        )
    if response.status_code >= 400:
        raise SandboxHTTPError(
            f"sandbox cancellation returned HTTP {response.status_code}: {response.text}"
        )
    try:
        record = response.json()
    except ValueError as exc:
        raise SandboxHTTPError(f"invalid sandbox cancellation response: {response.text}") from exc
    if not isinstance(record, dict):
        raise SandboxHTTPError(f"invalid sandbox cancellation response: {response.text}")
    return record


def _deadline_reached(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        raise SandboxHTTPError("invalid sandbox status response: missing queue_expires_at")
    try:
        deadline = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SandboxHTTPError(
            "invalid sandbox status response: malformed queue_expires_at"
        ) from exc
    return datetime.now(UTC) >= deadline


def _tool_error(message: str) -> dict[str, Any]:
    """The tool could not run at all — distinct from a command that ran and failed."""
    return {"success": False, "result": f"Error: {message}", "error": message, "outcome": "error"}


def _shell_outcome(data: dict[str, Any]) -> dict[str, Any]:
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
    return outcome


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


def _merge_committed_output_refs(result: dict[str, Any], output_refs: Any) -> dict[str, Any]:
    """Attach runner-committed object identities to activation artifact metadata."""
    if not isinstance(output_refs, list):
        return result
    committed = {
        str(item.get("relative_path") or ""): item
        for item in output_refs
        if isinstance(item, dict) and item.get("relative_path") and item.get("object_uri")
    }
    if not committed:
        return result
    merged = dict(result)
    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        merged_artifacts: list[Any] = []
        used: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                merged_artifacts.append(artifact)
                continue
            path = str(artifact.get("path") or artifact.get("relative_path") or "")
            reference = committed.get(path)
            merged_artifacts.append({**artifact, **reference} if reference else artifact)
            if reference:
                used.add(path)
        merged_artifacts.extend(
            reference for path, reference in committed.items() if path not in used
        )
        merged["artifacts"] = merged_artifacts
    else:
        merged["artifacts"] = list(committed.values())
    merged["output_refs"] = list(committed.values())
    return merged
