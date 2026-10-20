"""Processors run in the sandbox through the shell tool's execution path.

Each run is one signed ``POST /sandbox/executions`` in the processor's own
session, so the Go manager keeps one warm sandbox per processor and reaps it
when idle; the platform never creates or retires one. Network access is the
sandbox's policy, the same as for an agent's shell. The output is read back
from the session's files like the shell tool's.
"""

import asyncio
import json
import logging
from typing import Any, Protocol

import httpx
from agentarea_agents_sdk.tools.sandbox_control_auth import SandboxControlSigner
from agentarea_agents_sdk.tools.shell_toolset import wait_for_sandbox_execution
from agentarea_common.artifacts import S3WorkspaceRepository
from agentarea_common.config import Settings
from agentarea_common.outbound import Destination, outbound_client
from agentarea_streams.domain.errors import ProcessorRuntimeUnavailableError
from agentarea_streams.domain.processor import CodeRun

logger = logging.getLogger(__name__)

STDERR_MAX_BYTES = 4096
#: How long past the code's own timeout a run may take to queue, start and report.
DEFAULT_GRACE_S = 30.0


class SessionFiles(Protocol):
    async def get_object_ref(
        self, workspace_id: str, task_id: str, value: Any
    ) -> tuple[bytes, str | None]: ...


class SandboxCodeRunner:
    def __init__(
        self,
        *,
        manager_url: str,
        control_secret: str | None,
        files: SessionFiles,
        client: httpx.AsyncClient | None = None,
        poll_interval_s: float = 0.05,
        grace_s: float = DEFAULT_GRACE_S,
    ):
        if not manager_url:
            raise ValueError("Processors run in the sandbox; set AGENTAREA_MCP_MANAGER_URL")
        if not control_secret or len(control_secret.encode()) < 32:
            raise ValueError(
                "Processors run in the sandbox; AGENTAREA_SANDBOX_CONTROL_SECRET must be set "
                "to at least 32 bytes"
            )
        self._url = manager_url.rstrip("/")
        self._secret = control_secret
        self._files = files
        self._client = client
        self._poll_interval_s = poll_interval_s
        self._grace_s = grace_s

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = outbound_client(Destination.INTERNAL, timeout=30)
        return self._client

    async def run(
        self,
        *,
        workspace_id: str,
        session: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CodeRun:
        try:
            async with asyncio.timeout(timeout_seconds + self._grace_s):
                return await self._run(
                    workspace_id, session, command, timeout_seconds, max_output_bytes
                )
        except TimeoutError as error:
            raise ProcessorRuntimeUnavailableError(
                f"the sandbox did not answer within {timeout_seconds + self._grace_s:.0f}s"
            ) from error
        except ProcessorRuntimeUnavailableError:
            raise
        except Exception as error:
            logger.warning("Processor session %s could not run", session, exc_info=True)
            raise ProcessorRuntimeUnavailableError(
                f"the sandbox could not run it: {error}"
            ) from error

    async def _run(
        self,
        workspace_id: str,
        session: str,
        command: str,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> CodeRun:
        signer = SandboxControlSigner(
            secret=self._secret, workspace_id=workspace_id, task_id=session
        )
        body = json.dumps(
            {
                "workspace_id": workspace_id,
                "task_id": session,
                "command": {
                    "command_body": command,
                    "timeout_seconds": timeout_seconds,
                    "stdout_max_bytes": max_output_bytes,
                    "stderr_max_bytes": STDERR_MAX_BYTES,
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        headers = signer.headers("execution.create", body=body)
        headers["Content-Type"] = "application/json"
        client = self._http()
        created = await client.post(
            f"{self._url}/sandbox/executions", content=body, headers=headers
        )
        result = await wait_for_sandbox_execution(
            client=client,
            created=created,
            mcp_manager_url=self._url,
            signer=signer,
            poll_interval_s=self._poll_interval_s,
        )
        exit_code = int(result.get("exit_code", 0) or 0)
        return CodeRun(
            exit_code=exit_code,
            stdout=await self._read(workspace_id, session, result, "stdout"),
            stdout_truncated=bool(result.get("stdout_truncated")),
            stderr=await self._read(workspace_id, session, result, "stderr") if exit_code else "",
        )

    async def _read(
        self, workspace_id: str, session: str, result: dict[str, Any], stream: str
    ) -> str:
        reference = result.get(f"{stream}_ref")
        if not isinstance(reference, dict):
            return ""
        content, _ = await self._files.get_object_ref(workspace_id, session, reference)
        return content.decode("utf-8", errors="replace")


def processor_runner(settings: Settings) -> SandboxCodeRunner:
    secret = settings.sandbox.CONTROL_SECRET
    return SandboxCodeRunner(
        manager_url=settings.mcp.MANAGER_URL,
        control_secret=secret.get_secret_value() if secret is not None else None,
        files=S3WorkspaceRepository(),
    )
