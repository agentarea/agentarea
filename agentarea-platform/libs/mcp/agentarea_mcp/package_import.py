"""Import command-based MCP instances into immutable package images."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
from agentarea_common.config import get_database, get_settings

from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_mcp.transport_spec import merge_transport_spec, server_transport_spec

_PACKAGE_IMPORT_TIMEOUT_SECONDS = 20 * 60

_MCP_RETIRE_RETRIES = 5
_MCP_RETIRE_BASE_DELAY_SECONDS = 0.2
_MCP_RETIRE_MAX_DELAY_SECONDS = 1.0


class MCPRuntimeRetirementError(RuntimeError):
    """A transient runtime retirement failure that left desired state unchanged."""

    status_code = 503


class MCPRuntimeRetirementConflictError(MCPRuntimeRetirementError):
    """The manager could not retire this runtime before the retry window ended."""

    status_code = 409


def _now_iso() -> str:
    """Return a timezone-aware UTC timestamp for package import state."""
    return datetime.now(UTC).isoformat()


def _error_from_response(response: httpx.Response) -> str:
    """Extract a manager error without hiding malformed error responses."""
    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, str) and error.strip():
            return error

    return f"MCP manager package import returned HTTP {response.status_code}"


def _transport_error_message(exc: BaseException) -> str:
    """Keep transport failures useful when httpx provides no message."""
    message = str(exc).strip()
    if message:
        return message
    return type(exc).__name__


async def retire_runtime_before_mutation(
    instance_id: UUID,
    *,
    settings: Any | None = None,
) -> None:
    """Retire a running container before changing its desired specification."""
    if settings is None:
        settings = get_settings().mcp

    url = settings.manager_retire_url(instance_id)
    headers = settings.manager_gateway_headers()
    retryable = {409, 502, 503, 504}
    last_error: Exception | None = None
    saw_conflict = False

    async with httpx.AsyncClient(timeout=settings.MCP_CLIENT_TIMEOUT) as client:
        for attempt in range(_MCP_RETIRE_RETRIES):
            try:
                response = await client.delete(url, headers=headers)
                if response.status_code == 409:
                    saw_conflict = True
                if response.status_code == 204:
                    return
                if response.status_code not in retryable:
                    response.raise_for_status()
                last_error = RuntimeError(
                    f"MCP manager retirement returned HTTP {response.status_code}"
                )
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_error = exc
            if attempt + 1 < _MCP_RETIRE_RETRIES:
                delay = min(
                    _MCP_RETIRE_BASE_DELAY_SECONDS * (2**attempt),
                    _MCP_RETIRE_MAX_DELAY_SECONDS,
                )
                await asyncio.sleep(delay)

    if saw_conflict:
        raise MCPRuntimeRetirementConflictError(
            f"MCP runtime retirement for {instance_id} is still in progress; retry the mutation"
        ) from last_error
    raise MCPRuntimeRetirementError(
        f"MCP runtime retirement failed for {instance_id}; desired state was preserved"
    ) from last_error


async def _record_package_import(
    session,
    instance_id: UUID,
    *,
    status: str,
    error: str,
    source_spec: dict[str, Any],
) -> None:
    """Record a rejected or temporarily unavailable import attempt.

    An import runs for minutes; when the connection was edited meanwhile, the
    attempt no longer describes it, so nothing is recorded and the next sweep
    judges the edited connection afresh.
    """
    async with session.begin():
        instance = await MCPServerInstanceRepository.lock_for_package_import(
            session,
            instance_id,
        )
        if instance is None:
            raise ValueError(f"MCP instance {instance_id} not found")
        updated_spec = dict(source_spec)
        updated_spec["package_import"] = {
            "status": status,
            "error": error,
            "at": _now_iso(),
        }
        MCPServerInstanceRepository.update_locked_json_spec(
            instance,
            source_spec,
            updated_spec,
        )


async def _run_import(session, instance_id: UUID) -> None:
    """Run one manager import and persist its terminal platform state."""
    async with session.begin():
        instance = await MCPServerInstanceRepository.lock_for_package_import(
            session,
            instance_id,
        )
        if instance is None:
            raise ValueError(f"MCP instance {instance_id} not found")
        source_spec = dict(instance.json_spec or {})
        server = await MCPServerRepository.get_for_package_import(
            session,
            instance.server_spec_id,
        )
        if server is None:
            raise ValueError(f"MCP server spec {instance.server_spec_id} not found")
        effective_source_spec = merge_transport_spec(
            server_transport_spec(server),
            source_spec,
        )

    settings = get_settings().mcp
    manager_url = f"{settings.MCP_MANAGER_URL.rstrip('/')}/packages/import"
    headers = settings.manager_gateway_headers()
    try:
        async with httpx.AsyncClient(timeout=_PACKAGE_IMPORT_TIMEOUT_SECONDS) as client:
            response = await client.post(
                manager_url,
                headers=headers,
                json={"instance_id": str(instance_id)},
            )
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        await _record_package_import(
            session,
            instance_id,
            status="unavailable",
            error=_transport_error_message(exc),
            source_spec=source_spec,
        )
        return

    if response.status_code == 422:
        await _record_package_import(
            session,
            instance_id,
            status="rejected",
            error=_error_from_response(response),
            source_spec=source_spec,
        )
        return

    if response.status_code != 200:
        # 503 is the manager saying "later"; anything else is a manager or
        # platform bug. Either way the row waits out the retry interval
        # instead of being retried on every tick.
        await _record_package_import(
            session,
            instance_id,
            status="unavailable",
            error=_error_from_response(response),
            source_spec=source_spec,
        )
        return

    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("MCP manager package import response must be a JSON object")

    image = payload.get("image")
    command = payload.get("command")
    port = payload.get("port")
    package = payload.get("package")
    if not isinstance(image, str) or not image.strip():
        raise ValueError("MCP manager package import response has no image")
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError("MCP manager package import response command must be a list of strings")
    if not isinstance(port, int):
        raise ValueError("MCP manager package import response port must be an integer")
    if not isinstance(package, dict):
        raise ValueError("MCP manager package import response package must be an object")

    old_args = effective_source_spec.get("args", [])
    if not isinstance(old_args, list):
        raise ValueError("Command instance args must be a list before package import")

    converted_spec = {
        key: value
        for key, value in source_spec.items()
        if key not in {"command", "args", "cmd", "type", "package_import"}
    }
    converted_spec.update(
        {
            "type": "docker",
            "image": image,
            "port": port,
            "command": list(command),
            "package": package,
            "source": {
                "type": "command",
                "command": effective_source_spec.get("command"),
                "args": list(old_args),
            },
        }
    )

    async with session.begin():
        instance = await MCPServerInstanceRepository.lock_for_package_import(
            session,
            instance_id,
        )
        if instance is None:
            raise ValueError(f"MCP instance {instance_id} not found")
        if instance.json_spec != source_spec:
            # Edited while the image was built: the image may still be right,
            # but the conversion would drop the edit. The next sweep imports
            # the edited connection, and finds the image by its tag.
            return
        await retire_runtime_before_mutation(instance_id)
        MCPServerInstanceRepository.update_locked_json_spec(
            instance,
            source_spec,
            converted_spec,
        )


async def import_package_image(instance_id: UUID, session=None) -> None:
    """Import one verified command instance through the MCP manager."""
    if session is not None:
        await _run_import(session, instance_id)
        return

    db = get_database()
    async with db.async_session_factory() as managed_session:
        await _run_import(managed_session, instance_id)
