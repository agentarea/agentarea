"""Shell tool that routes commands to a sandboxed bash executor.

The agent sees a single ``bash(command)`` method. Where the command actually
runs — a dev sandbox container, a K8s warm pool pod, a future microVM — is
hidden behind ``mcp_manager_url``. The toolset itself is a thin HTTP client.

Per-task state isolation is handled by an injected
:class:`ToolInvocationContext`: the activity layer constructs it from the
Temporal task's identity (``activity.info().workflow_id``) and hands it to
the toolset at construction time. The toolset reads ``ctx.workflow_id`` to
scope the sandbox call. Without a ctx (standalone SDK use, unit tests),
calls fall through to the stateless sandbox path. The toolset has no
knowledge of Temporal — it just consumes a value object.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .decorator_tool import Toolset, tool_method
from .invocation_context import ToolInvocationContext, empty_context
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
    """Single-method toolset wrapping the sandbox /sandbox/execute endpoint."""

    def __init__(
        self,
        mcp_manager_url: str | None = None,
        ctx: ToolInvocationContext | None = None,
        http_client: Any = None,
    ) -> None:
        super().__init__()
        self._mcp_manager_url = (mcp_manager_url or "").rstrip("/")
        self._ctx = ctx or empty_context()
        self._http_client = http_client

    @tool_method
    async def bash(self, command: str, timeout_seconds: int = 30) -> str:
        """Run a bash command and return stdout, stderr, and exit code."""
        if not self._mcp_manager_url:
            return "Error: shell tool is not configured (mcp_manager_url missing)"
        if not isinstance(command, str) or not command.strip():
            return "Error: command must be a non-empty string"
        if timeout_seconds <= 0 or timeout_seconds > 300:
            timeout_seconds = 30

        payload: dict[str, Any] = {
            "script_name": "cmd.sh",
            "script_content": command,
            "timeout_seconds": timeout_seconds,
        }
        if self._ctx.workflow_id:
            payload["workflow_id"] = self._ctx.workflow_id

        url = f"{self._mcp_manager_url}/sandbox/execute"
        try:
            client = self._http_client
            owned = False
            if client is None:
                client = httpx.AsyncClient(timeout=timeout_seconds + 10)
                owned = True
            try:
                resp = await client.post(url, json=payload)
            finally:
                if owned:
                    await client.aclose()
        except httpx.HTTPError as exc:
            logger.exception("bash request to %s failed", url)
            return f"Error: failed to reach sandbox: {exc}"

        if resp.status_code >= 400:
            return f"Error: sandbox returned HTTP {resp.status_code}: {resp.text}"

        try:
            data = resp.json()
        except ValueError:
            return f"Error: invalid sandbox response: {resp.text}"

        return _format_result(data)


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
