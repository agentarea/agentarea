"""verify() — end-to-end trial-run for an MCP server instance.

Replaces the Temporal StartMCPInstanceWorkflow.  Designed to be called from:
  - MCPContainerMonitor sweep (never_attempted rows)
  - service.verify_instance (user-initiated re-verify)

Row-level locking via SELECT … FOR UPDATE prevents two concurrent verify()
calls on the same instance from both re-running the expensive provisioning
path.
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from agentarea_common.config import get_database, get_settings
from sqlalchemy import select

from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.verification_types import (
    VERIFICATION_SCHEMA_VERSION,
    VerificationError,
    VerificationPayload,
)

logger = logging.getLogger(__name__)

_LIST_TOOLS_ATTEMPT_TIMEOUT = 5  # seconds per attempt
_LIST_TOOLS_BACKOFF_DELAYS = [2, 4, 8, 16, 30, 30]  # seconds between retries
_TOTAL_DEADLINE = 120  # seconds total budget (cold image pulls can take 60-90s)


def _transport_spec_from_server(server: MCPServer) -> dict:
    spec = dict(server.json_spec or {})
    if server.remote_url:
        spec.setdefault("type", "url")
        spec.setdefault("endpoint_url", server.remote_url)
    elif server.cmd:
        spec.setdefault("type", "command")
        spec.setdefault("command", server.cmd[0] if server.cmd else "")
        if len(server.cmd or []) > 1:
            spec.setdefault("args", list(server.cmd[1:]))
    elif server.docker_image_url:
        spec.setdefault("type", "docker")
        spec.setdefault("image", server.docker_image_url)
    else:
        spec.setdefault("type", "docker")
    return spec


class _RuntimeInstance:
    def __init__(self, instance: MCPServerInstance, transport_spec: dict):
        self.id = instance.id
        self.name = instance.name
        self.workspace_id = instance.workspace_id
        self.created_by = instance.created_by
        self.verification = instance.verification
        self.last_dispatch = instance.last_dispatch
        self.tools = instance.tools
        self.server_spec_id = instance.server_spec_id
        self.json_spec = {**transport_spec, **(instance.json_spec or {})}

    @property
    def endpoint_url(self) -> str:
        instance_type = self.json_spec.get("type", "docker")
        if instance_type == "url":
            return self.json_spec.get("endpoint_url", "")
        if instance_type in ("docker", "command"):
            resolved = self.json_spec.get("internal_url")
            if isinstance(resolved, str) and "://" in resolved:
                return resolved
            port = 8080 if instance_type == "command" else self.json_spec.get("port") or 8000
            return f"http://mcp-{self.id}:{port}"
        raise ValueError("bundle has no endpoint_url")


_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionRefusedError,
    TimeoutError,
    asyncio.TimeoutError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    OSError,
)


def _iter_leaf_exceptions(exc: BaseException):
    """Yield leaf exceptions from possibly-nested BaseExceptionGroup.

    anyio/mcp wrap transport errors in TaskGroup → BaseExceptionGroup; the raw
    `str(exc)` on the group is useless ('unhandled errors in a TaskGroup (N
    sub-exceptions)'). We walk the group to surface the real cause.
    """
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _iter_leaf_exceptions(inner)
    else:
        yield exc


def _classify_list_tools_error(exc: BaseException) -> tuple[bool, BaseException]:
    """Return (is_transient, best_leaf_exception).

    Prefers a transient leaf (so we retry) over a non-transient one when both
    are present in a group.
    """
    leaves = list(_iter_leaf_exceptions(exc))
    for leaf in leaves:
        if isinstance(leaf, _TRANSIENT_EXCEPTIONS):
            return True, leaf
    return False, leaves[0] if leaves else exc


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _make_payload(
    status: str,
    error: VerificationError | None = None,
) -> VerificationPayload:
    return VerificationPayload(
        schema_version=VERIFICATION_SCHEMA_VERSION,
        status=status,  # type: ignore[arg-type]
        at=_now_iso(),
        error=error,
    )


async def _list_tools(endpoint_url: str, headers: dict | None = None) -> list[dict]:
    """Connect to running MCP server and list tools.

    URL transport selection:
    - URL ends with /sse  → SSE transport only (preserves explicit intent)
    - URL ends with /mcp  → streamable-HTTP, fall back to sibling /sse
    - URL has no suffix   → try <url>/mcp, fall back to <url>/sse

    Raises on any connection or protocol error — caller handles retries.
    """
    from mcp import ClientSession

    url = endpoint_url.rstrip("/")
    custom_headers = dict(headers) if headers else None
    timeout_seconds = float(_LIST_TOOLS_ATTEMPT_TIMEOUT)

    # Decide transport(s) based on URL suffix.
    if url.endswith("/sse"):
        streamable_url: str | None = None
        sse_url: str = url
    elif url.endswith("/mcp"):
        streamable_url = url
        sse_url = url[:-4] + "/sse"
    else:
        streamable_url = f"{url}/mcp"
        sse_url = f"{url}/sse"

    result = None
    if streamable_url is not None:
        try:
            from mcp.client.streamable_http import streamablehttp_client

            async with streamablehttp_client(
                streamable_url,
                timeout=timeout_seconds,
                headers=custom_headers,
            ) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as sess:
                    await sess.initialize()
                    result = await sess.list_tools()
        except Exception as transport_err:
            logger.debug(
                "Streamable HTTP failed for %s (%s), trying SSE at %s",
                streamable_url,
                transport_err,
                sse_url,
            )

    if result is None:
        from mcp.client.sse import sse_client

        async with sse_client(
            sse_url,
            timeout=timeout_seconds,
            headers=custom_headers,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as sess:
                await sess.initialize()
                result = await sess.list_tools()

    return [
        {
            "name": t.name,
            "description": t.description or "",
            "inputSchema": t.inputSchema if t.inputSchema else {},
        }
        for t in result.tools
    ]


async def _go_create_instance(instance: MCPServerInstance, mcp_manager_url: str) -> dict:
    """POST /instances to Go manager (ack only); returns status_code, body, and internal_url."""
    payload = {
        "instance_id": str(instance.id),
        "name": instance.name,
        "service_name": str(instance.id),
        "json_spec": instance.json_spec,
        "workspace_id": str(instance.workspace_id),
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(f"{mcp_manager_url}/instances", json=payload)
        body = resp.json() if resp.content else {}
        internal_url = None
        if isinstance(body, dict):
            internal_url = body.get("internal_url") or body.get("url")
        return {
            "status_code": resp.status_code,
            "body": body,
            "internal_url": internal_url,
        }


async def _go_health(instance_id: str, mcp_manager_url: str) -> dict:
    """GET /instances/{id}/health from Go manager."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(f"{mcp_manager_url}/instances/{instance_id}/health")
        if resp.status_code == 200:
            return resp.json()
        return {"healthy": False, "state": "error", "details": {}}


async def verify(
    instance: MCPServerInstance,
    session=None,
    *,
    extra_headers: dict[str, str] | None = None,
    _list_tools_fn=None,  # test seam
    _go_create_fn=None,  # test seam
    _go_health_fn=None,  # test seam
) -> VerificationPayload:
    """End-to-end verification of an MCP server instance.

    Acquires a row-level lock so that a concurrent call (monitor sweep + user
    click arriving simultaneously) does not re-run the full provisioning path.
    The second caller re-reads the row after the lock is released and returns
    whatever the first caller wrote.

    Args:
        instance: The MCPServerInstance ORM object.
        session: An open AsyncSession.  If None, a new session is created.
        extra_headers: Optional headers merged into the verification HTTP probe
            (e.g. caller-supplied Authorization for ad-hoc URL checks).
        _list_tools_fn / _go_create_fn / _go_health_fn: Test seams.

    Returns:
        VerificationPayload with the final status written to the DB.
    """
    if (instance.json_spec or {}).get("type") == "bundle":
        raise NotImplementedError("Bundle verification is derived at read time")

    list_tools_fn = _list_tools_fn or _list_tools
    go_create_fn = _go_create_fn or _go_create_instance
    go_health_fn = _go_health_fn or _go_health

    settings = get_settings()
    mcp_manager_url = settings.mcp.MCP_MANAGER_URL

    instance_id = str(instance.id)

    db = get_database()

    # If caller supplies a session we use it; otherwise open a new one.
    # The lock must be acquired inside a transaction.
    async def _run(sess) -> VerificationPayload:
        async with sess.begin():
            # Row-level lock — only one verify() progresses at a time.
            locked = (
                await sess.execute(
                    select(MCPServerInstance)
                    .where(MCPServerInstance.id == instance.id)
                    .with_for_update()
                )
            ).scalar_one_or_none()

            if locked is None:
                logger.warning("verify: instance %s not found", instance_id)
                return _make_payload(
                    "failed",
                    VerificationError(
                        code="instance_not_found",
                        message="Instance was deleted before verification could start.",
                        detail=None,
                    ),
                )

            server_spec = (
                await sess.execute(select(MCPServer).where(MCPServer.id == locked.server_spec_id))
            ).scalar_one_or_none()
            if server_spec is None:
                payload = _make_payload(
                    "failed",
                    VerificationError(
                        code="server_spec_not_found",
                        message="Referenced MCP server spec was not found.",
                        detail=str(locked.server_spec_id),
                    ),
                )
                locked.verification = dict(payload)
                await sess.flush()
                return payload

            runtime_instance = _RuntimeInstance(locked, _transport_spec_from_server(server_spec))
            instance_type = runtime_instance.json_spec.get("type", "docker")
            if instance_type == "bundle":
                raise NotImplementedError("Bundle verification is derived at read time")

            # If another concurrent verify() is already in progress on this row,
            # return its current state — the in-flight caller will write the final
            # result. Terminal states (succeeded/failed) fall through: the user
            # clicked Verify precisely to re-run.
            if locked.verification.get("status") == "in_progress":
                logger.info(
                    "verify: instance %s already in_progress, skipping",
                    instance_id,
                    extra={"instance_id": instance_id, "type": instance_type},
                )
                return VerificationPayload(**locked.verification)

            # Mark in_progress atomically while holding the lock.
            in_progress: VerificationPayload = _make_payload("in_progress")
            locked.verification = dict(in_progress)
            await sess.flush()

        # --- Lock released — do the expensive work outside the transaction ---
        logger.info(
            "verify: starting",
            extra={"instance_id": instance_id, "type": instance_type, "stage": "start"},
        )

        # Step 1 — for docker/command, ask Go manager to provision (ack-only).
        resolved_url: str | None = None
        if instance_type in ("docker", "command"):
            try:
                ack = await go_create_fn(runtime_instance, mcp_manager_url)
                sc = ack["status_code"]
                resolved_url = ack.get("internal_url")
                if sc not in (200, 201, 409):
                    body = ack.get("body", {})
                    # Go manager shape: {"error": "<semantic_code>", "code": <http_status>, "message": "..."}
                    # Prefer the semantic string from `error`; `code` is the HTTP status echo.
                    raw_code = body.get("error") or body.get("code") or "provision_failed"
                    error_code = str(raw_code)
                    error_msg = body.get("message") or f"Go manager returned HTTP {sc}"
                    payload = _make_payload(
                        "failed",
                        VerificationError(
                            code=error_code,
                            message=error_msg,
                            detail=str(body) if body else None,
                        ),
                    )
                    await _save_verification(locked.id, payload, db)
                    logger.warning(
                        "verify: go ack failed",
                        extra={
                            "instance_id": instance_id,
                            "type": instance_type,
                            "stage": "go_ack",
                            "error_code": error_code,
                        },
                    )
                    return payload
            except Exception:
                logger.exception(
                    "verify: go create raised",
                    extra={"instance_id": instance_id, "type": instance_type, "stage": "go_ack"},
                )
                payload = _make_payload(
                    "failed",
                    VerificationError(
                        code="provision_error",
                        message="Error communicating with Go manager during provisioning.",
                        detail=None,
                    ),
                )
                await _save_verification(locked.id, payload, db)
                return payload

        # Step 2 — retry list_tools with exponential backoff within 60s budget.
        # Prefer a full URL the Go manager told us it provisioned (K8s backend:
        # `http://mcp-<name>.<ns>.svc.cluster.local:<port>`). Docker backend
        # returns a path like `/mcp/<slug>` for traefik routing — those aren't
        # directly usable as a transport URL, so we ignore them and let the
        # domain model compute the direct-container address.
        if resolved_url and "://" in resolved_url:
            endpoint_url = resolved_url
            await _persist_internal_url(locked.id, resolved_url, db)
        else:
            endpoint_url = runtime_instance.endpoint_url
        headers = dict(runtime_instance.json_spec.get("headers", {}))
        if extra_headers:
            headers.update(extra_headers)
        deadline = asyncio.get_event_loop().time() + _TOTAL_DEADLINE
        last_error: BaseException | None = None

        for delay in _LIST_TOOLS_BACKOFF_DELAYS:
            try:
                async with asyncio.timeout(_LIST_TOOLS_ATTEMPT_TIMEOUT):
                    tools = await list_tools_fn(endpoint_url, headers or None)

                payload = _make_payload("succeeded")
                async with db.async_session_factory() as save_sess:
                    async with save_sess.begin():
                        row = (
                            await save_sess.execute(
                                select(MCPServerInstance).where(MCPServerInstance.id == locked.id)
                            )
                        ).scalar_one()
                        row.verification = dict(payload)
                        row.tools = tools

                logger.info(
                    "verify: succeeded",
                    extra={
                        "instance_id": instance_id,
                        "type": instance_type,
                        "stage": "list_tools",
                        "result": "succeeded",
                        "tools_count": len(tools),
                    },
                )
                return payload

            except BaseException as e:
                is_transient, leaf = _classify_list_tools_error(e)
                if is_transient:
                    last_error = leaf
                    logger.debug(
                        "verify: list_tools transient error (will retry): %s: %s",
                        type(leaf).__name__,
                        leaf,
                        extra={"instance_id": instance_id, "delay": delay},
                    )
                    if asyncio.get_event_loop().time() + delay > deadline:
                        break
                    await asyncio.sleep(delay)
                    continue

                # MCP protocol-level error — fail fast, no retry.
                message = f"{type(leaf).__name__}: {leaf}" if str(leaf) else type(leaf).__name__
                payload = _make_payload(
                    "failed",
                    VerificationError(
                        code="mcp_error",
                        message=message,
                        detail=None,
                    ),
                )
                await _save_verification(locked.id, payload, db)
                logger.warning(
                    "verify: mcp protocol error: %s",
                    message,
                    extra={
                        "instance_id": instance_id,
                        "type": instance_type,
                        "stage": "list_tools",
                        "result": "failed",
                        "error_code": "mcp_error",
                    },
                )
                return payload

        # Step 3 — deadline exhausted; enrich error via health endpoint.
        error_code = "list_tools_timeout"
        error_msg = f"MCP did not respond within {_TOTAL_DEADLINE}s: {last_error}"

        if instance_type in ("docker", "command"):
            try:
                health = await go_health_fn(instance_id, mcp_manager_url)
                if health.get("state") == "error":
                    error_code = "container_failed"
                    detail = health.get("details") or health.get("message")
                    error_msg = str(detail) if detail else "Container entered error state."
                elif not health.get("healthy", False):
                    error_code = "container_not_ready"
                    error_msg = f"Container not ready: state={health.get('state', 'unknown')}"
            except Exception:
                logger.exception(
                    "verify: health check raised (non-fatal)",
                    extra={"instance_id": instance_id, "stage": "post_timeout_health"},
                )

        payload = _make_payload(
            "failed",
            VerificationError(code=error_code, message=error_msg, detail=None),
        )
        await _save_verification(locked.id, payload, db)
        logger.warning(
            "verify: failed",
            extra={
                "instance_id": instance_id,
                "type": instance_type,
                "stage": "list_tools",
                "result": "failed",
                "error_code": error_code,
            },
        )
        return payload

    if session is not None:
        return await _run(session)

    async with db.async_session_factory() as sess:
        return await _run(sess)


async def _save_verification(instance_id, payload: VerificationPayload, db) -> None:
    """Persist a VerificationPayload to the DB in its own transaction."""
    async with db.async_session_factory() as sess:
        async with sess.begin():
            row = (
                await sess.execute(
                    select(MCPServerInstance).where(MCPServerInstance.id == instance_id)
                )
            ).scalar_one_or_none()
            if row is not None:
                row.verification = dict(payload)


async def _persist_internal_url(instance_id, internal_url: str, db) -> None:
    """Persist the Go-manager-reported internal URL into json_spec.

    Doing so decouples `endpoint_url` from guessing the service name / port —
    the Go backend knows the real address because it created the Service.
    """
    async with db.async_session_factory() as sess:
        async with sess.begin():
            row = (
                await sess.execute(
                    select(MCPServerInstance).where(MCPServerInstance.id == instance_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return
            spec = dict(row.json_spec or {})
            if spec.get("internal_url") == internal_url:
                return
            spec["internal_url"] = internal_url
            row.json_spec = spec
