"""Shell tool that routes commands to a sandboxed bash executor.

The agent sees a single ``bash(command)`` method. Where the command actually
runs — a dev sandbox container, a K8s warm pool pod, a future microVM — is
hidden behind ``mcp_manager_url``. The toolset talks to the sandbox control
plane and waits for the data-plane runner to complete the execution.

Per-task state isolation is handled by an injected
:class:`ToolInvocationContext`. A canonical task workspace is mandatory: commands
without a repository, workspace ID, task ID, and immutable manifest ref are
rejected before reaching the control plane. The toolset has no knowledge of
Temporal — it just consumes a value object.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
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
PACKAGE_INSTALL_PROFILES = frozenset({"allowed", "locked"})
# Upper bound on a single bash-produced artifact copied out to durable storage.
# Matches the executor's file-API content ceiling: reads above it fail at the
# sandbox anyway, so a larger file is refused loudly rather than half-copied.
# Larger deliverables need a streaming path (not built yet) — see copy-out.
MAX_DURABLE_ARTIFACT_BYTES = 16 * 1024 * 1024
# Aggregate ceiling on a task's durable workspace. A per-file cap alone leaves
# N*16MB unbounded; this bounds the whole task so one run cannot fill the store.
MAX_DURABLE_TASK_BYTES = 1024 * 1024 * 1024


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
        http_client: Any = None,
    ) -> None:
        super().__init__()
        self._mcp_manager_url = (mcp_manager_url or "").rstrip("/")
        self._ctx = ctx or empty_context()
        self._workspace_repository = workspace_repository
        self._workspace_id = workspace_id or self._ctx.workspace_id
        self._task_id = task_id or self._ctx.task_id
        self._http_client = http_client
        self._inputs_materialized = False

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
        package_install = (self._ctx.metadata or {}).get("package_install", "allowed")
        if package_install not in PACKAGE_INSTALL_PROFILES:
            return _tool_error(f"invalid package_install profile: {package_install}")

        command_payload: dict[str, Any] = {"timeout_seconds": timeout_seconds}
        if requested_artifacts:
            command_payload["artifact_paths"] = requested_artifacts
        if self._ctx.workflow_id:
            command_payload["workflow_id"] = self._ctx.workflow_id
        try:
            await self._stage_inputs()
            await self._materialize_inputs()
        except Exception as exc:
            logger.exception("failed to stage task workspace inputs")
            return _tool_error(f"failed to prepare workspace: {exc}")
        command_payload["command_body"] = command

        payload: dict[str, Any] = {
            "workflow_id": self._ctx.workflow_id,
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "runtime": {
                "provider": "agentarea-k8s",
                "package_install": package_install,
            },
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

        try:
            data = await self._resolve_output_refs(data)
        except Exception as exc:
            logger.exception("sandbox returned invalid output references")
            return _tool_error(f"sandbox returned invalid output references: {exc}")

        if not requested_artifacts and not data.get("artifacts") and not data.get("output_refs"):
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

    async def _stage_inputs(self) -> None:
        """Stage optional trusted project inputs into the task workspace.

        The command body itself travels inline in the execution request. Only
        large project inputs, when requested, are migrated directly between the
        trusted repository and object storage — never through Redis.
        """
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

    async def _materialize_inputs(self) -> None:
        """Copy the task's durable inputs into the sandbox's live workspace.

        The mirror of copy-out: the agent works in one directory, so durable
        input files must land in the sandbox filesystem at the same relative
        path before bash runs. Reads each input's bytes from the trusted
        workspace repository and writes them through the /sandbox/files proxy,
        the same filesystem bash executes against. Runs once per session — the
        session workspace persists the files across later bash calls. No durable
        inputs is the legitimate empty case, not a fallback.
        """
        if self._inputs_materialized:
            return
        if self._workspace_repository is None or not self._workspace_id or not self._task_id:
            return
        inputs = await self._workspace_repository.list(
            self._workspace_id,
            self._task_id,
            prefix="inputs",
        )
        for obj in inputs:
            relative_path = obj.path
            if not relative_path.startswith("inputs/"):
                continue
            content, _ = await self._workspace_repository.get(
                self._workspace_id,
                self._task_id,
                relative_path,
            )
            await self._write_sandbox_file(relative_path, content)
        self._inputs_materialized = True

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

    async def _format_result_with_artifacts(self, data: dict[str, Any]) -> dict[str, Any]:
        artifact_refs: list[dict[str, Any]] = []
        artifacts = data.get("artifacts") or data.get("output_refs") or []
        # Budget for copy-out this call: how many more durable bytes this task may
        # take. Computed once from the current task size; decremented as each
        # artifact is persisted so one call cannot blow past the per-task quota.
        quota_remaining = await self._durable_bytes_remaining()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            requested_path = str(
                artifact.get("relative_path")
                or artifact.get("path")
                or artifact.get("requested_path")
                or ""
            )
            entry: dict[str, Any] = {
                "requested_path": requested_path,
                "size": artifact.get("size") or 0,
                "content_type": artifact.get("content_type"),
            }
            if artifact.get("error"):
                entry["error"] = artifact.get("error")
                artifact_refs.append(entry)
                continue

            object_uri = artifact.get("object_uri") or artifact.get("uri")
            if not object_uri:
                # A deliverable the agent created via bash lives only on the
                # ephemeral sandbox disk. Copy it out to the durable task
                # workspace NOW — synchronously, before this tool returns and
                # thus before the agent can claim completion (copy-before-claim).
                # This is the only path by which a binary produced via bash
                # becomes durable and retrievable through the /files API.
                try:
                    persisted = await self._persist_artifact(
                        requested_path,
                        artifact.get("content_type"),
                        int(artifact.get("size") or 0),
                        expected_sha=str(artifact.get("sha256") or ""),
                        quota_remaining=quota_remaining,
                    )
                except Exception as exc:
                    logger.exception("failed to persist bash artifact %r", requested_path)
                    entry["error"] = f"failed to persist artifact durably: {exc}"
                    artifact_refs.append(entry)
                    continue
                persisted_size = int(getattr(persisted, "size", 0) or 0)
                quota_remaining -= persisted_size
                entry["size"] = persisted_size
                artifact = {
                    **artifact,
                    "object_uri": persisted.object_uri,
                    "object_version_or_etag": getattr(persisted, "object_version_or_etag", None),
                    "sha256": persisted.sha256,
                    "generation": getattr(persisted, "generation", None),
                }
                object_uri = persisted.object_uri
            entry.update(
                {
                    "artifact_path": requested_path,
                    "relative_path": requested_path,
                    "object_uri": object_uri,
                    "object_version_or_etag": artifact.get("object_version_or_etag")
                    or artifact.get("version_id")
                    or artifact.get("etag"),
                    "sha256": artifact.get("sha256"),
                    "generation": artifact.get("generation"),
                }
            )
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

    async def _durable_bytes_remaining(self) -> int:
        """How many more durable bytes this task may take (per-task quota headroom)."""
        if self._workspace_repository is None or not self._workspace_id or not self._task_id:
            return MAX_DURABLE_TASK_BYTES
        objects = await self._workspace_repository.list(self._workspace_id, self._task_id)
        used = sum(int(getattr(obj, "size", 0) or 0) for obj in objects)
        return max(0, MAX_DURABLE_TASK_BYTES - used)

    async def _persist_artifact(
        self,
        relative_path: str,
        content_type: str | None,
        size: int,
        *,
        expected_sha: str = "",
        quota_remaining: int = MAX_DURABLE_TASK_BYTES,
    ):
        """Copy one bash-produced file out of the sandbox into durable storage.

        Reads the bytes from the sandbox's live workspace and commits them to the
        durable, user-visible task workspace via the trusted repository (the same
        path the file tool's write-through uses, so /files lists it). Fails loudly
        — a deliverable the user cannot reach is a silent loss.
        """
        if self._workspace_repository is None:
            raise RuntimeError("workspace repository is not configured")
        if not self._workspace_id or not self._task_id:
            raise RuntimeError("workspace_id and task_id are required to persist artifacts")
        if not relative_path:
            raise RuntimeError("artifact has no path")
        # Defense in depth on the read key (the durable write key is normalized by
        # the repository sink). Refuse an absolute path, a parent-traversal
        # segment, or a NUL before it reaches the /sandbox/files proxy.
        if (
            relative_path.startswith("/")
            or "\x00" in relative_path
            or ".." in PurePosixPath(relative_path).parts
        ):
            raise RuntimeError(f"unsafe artifact path {relative_path!r}; not persisted")
        if size > MAX_DURABLE_ARTIFACT_BYTES:
            raise RuntimeError(
                f"artifact is {size} bytes, over the {MAX_DURABLE_ARTIFACT_BYTES}-byte "
                "durability cap; not persisted"
            )
        if size > quota_remaining:
            raise RuntimeError(
                f"artifact is {size} bytes but only {quota_remaining} bytes remain of the "
                f"{MAX_DURABLE_TASK_BYTES}-byte task durability quota; not persisted"
            )
        content = await self._read_sandbox_file(relative_path)
        # The executor hashed the file it discovered; recompute over the bytes we
        # actually read and refuse a mismatch, so a swap in the live workspace
        # between report and read cannot commit content the executor never saw.
        if expected_sha:
            actual_sha = hashlib.sha256(content).hexdigest()
            if actual_sha != expected_sha:
                raise RuntimeError(
                    f"artifact bytes changed between report and read "
                    f"(sha256 {actual_sha} != declared {expected_sha}); not persisted"
                )
        return await self._workspace_repository.put(
            self._workspace_id,
            self._task_id,
            relative_path,
            content,
            content_type,
        )

    async def _write_sandbox_file(self, relative_path: str, content: bytes) -> None:
        """Write a file into the sandbox's live workspace via the control plane.

        The write mirror of ``_read_sandbox_file``: the control plane signs the
        sandbox token and proxies the PUT to the executor, which writes the file
        into the same per-task session workspace bash runs in. No secret lives
        here. A non-2xx (e.g. 503 when the backend has no per-task file routing
        yet) is surfaced, never silently swallowed.
        """
        url = f"{self._mcp_manager_url}/sandbox/files"
        payload = {
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "path": relative_path,
            "content_base64": base64.b64encode(content).decode("ascii"),
        }
        client = self._http_client
        owned = False
        if client is None:
            client = httpx.AsyncClient(timeout=30)
            owned = True
        try:
            response = await client.request("PUT", url, json=payload)
        finally:
            if owned:
                await client.aclose()
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(
                f"sandbox file write failed for {relative_path!r}: HTTP {response.status_code}"
            )

    async def _read_sandbox_file(self, relative_path: str) -> bytes:
        """Read a file from the sandbox's live workspace via the control plane.

        The control plane signs the sandbox token and proxies to the executor;
        no secret lives here. A 503 means the backend has no per-task file
        routing yet (K8s warm-pool sticky routing) — surfaced, never silently
        swallowed.
        """
        url = f"{self._mcp_manager_url}/sandbox/files"
        params = {
            "workspace_id": self._workspace_id,
            "task_id": self._task_id,
            "path": relative_path,
        }
        client = self._http_client
        owned = False
        if client is None:
            client = httpx.AsyncClient(timeout=30)
            owned = True
        try:
            response = await client.request("GET", url, params=params)
        finally:
            if owned:
                await client.aclose()
        if response.status_code == 404:
            raise FileNotFoundError(relative_path)
        if response.status_code >= 400:
            # Do not echo the upstream response body into an agent-visible error.
            raise RuntimeError(
                f"sandbox file read failed for {relative_path!r}: HTTP {response.status_code}"
            )
        body = response.json()
        encoded = body.get("content_base64")
        if not isinstance(encoded, str):
            raise RuntimeError(f"sandbox file read returned no content for {relative_path!r}")
        content = base64.b64decode(encoded)
        # Bound the ACTUAL bytes, independent of the pre-read self-reported size:
        # a misreported size must not let the worker buffer/commit an oversized object.
        if len(content) > MAX_DURABLE_ARTIFACT_BYTES:
            raise RuntimeError(
                f"sandbox file {relative_path!r} is {len(content)} bytes, over the "
                f"{MAX_DURABLE_ARTIFACT_BYTES}-byte durability cap; not persisted"
            )
        return content


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

    if "id" not in record:
        raise SandboxHTTPError("invalid sandbox response: missing execution id")

    deadline = time.monotonic() + timeout_seconds + 60
    while True:
        status = record.get("status")
        if status == "completed":
            result = record.get("result")
            if isinstance(result, dict):
                return _merge_committed_output_refs(result, record.get("output_refs"))
            return record
        if status in {"failed", "cancelled"}:
            message = record.get("error") or status
            raise SandboxHTTPError(f"sandbox execution {status}: {message}")

        if time.monotonic() >= deadline:
            raise SandboxHTTPError(
                f"sandbox execution timed out waiting for completion: {record.get('id')}"
            )

        resp = await client.get(f"{mcp_manager_url}/sandbox/executions/{record['id']}")
        if resp.status_code >= 400:
            raise SandboxHTTPError(f"sandbox status returned HTTP {resp.status_code}: {resp.text}")
        try:
            record = resp.json()
        except ValueError as exc:
            raise SandboxHTTPError(f"invalid sandbox status response: {resp.text}") from exc

        if record.get("status") not in {"completed", "failed", "cancelled"}:
            await asyncio.sleep(2)


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
