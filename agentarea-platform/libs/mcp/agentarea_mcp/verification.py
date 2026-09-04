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
from agentarea_mcp.tool_serialization import serialize_mcp_tool

logger = logging.getLogger(__name__)

_LIST_TOOLS_ATTEMPT_TIMEOUT = 5  # seconds per attempt
_LIST_TOOLS_RETRY_DELAY = 5  # steady poll interval while the container provisions
# Absolute safety cap. Verification is liveness-driven: while a docker/command
# container is alive and still provisioning (pulling its image, or running a
# cold `uvx`/`npx` install that can take minutes) we keep polling list_tools and
# do NOT fail on a wall-clock. We only fail early when the runtime reports the
# container actually died. This cap is the backstop against a genuinely wedged
# container that never errors and never becomes ready.
_SAFETY_DEADLINE = 600  # seconds


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
        """Direct endpoint for URL-type servers only.

        Container-backed verification goes through the manager gateway (see
        verify()), so this must never synthesize a workload address — doing so
        would skip the gateway's on-demand start and request lease.
        """
        instance_type = self.json_spec.get("type", "docker")
        if instance_type == "url":
            return self.json_spec.get("endpoint_url", "")
        if instance_type in ("docker", "command", "kubernetes"):
            raise ValueError(
                f"container-backed MCP instance {self.id} has no direct endpoint; "
                "verification must go through the manager gateway"
            )
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


def declared_remote_transport(spec: dict | None) -> str | None:
    """Declared MCP wire transport from a ServerJSON-style spec, else None.

    Registry entries carry ``remotes: [{"type": "streamable-http"|"sse", "url": ...}]``.
    When present this is authoritative — we connect with exactly that transport
    and skip URL probing. Returns None for manually-entered URLs (unknown), where
    probing is the only option.
    """
    if not isinstance(spec, dict):
        return None
    remotes = spec.get("remotes")
    if isinstance(remotes, list):
        for remote in remotes:
            if isinstance(remote, dict) and remote.get("type"):
                return str(remote["type"])
    return None


def mcp_transport_candidates(
    endpoint_url: str, transport: str | None = None
) -> tuple[list[str], str | None]:
    """Ordered streamable-HTTP candidate URLs plus the SSE fallback URL (or None).

    Single source of truth for URL→transport selection across verification and
    runtime tool calls.

    When ``transport`` is declared by the registry spec, honor it exactly (no
    probing): ``streamable-http`` → connect at the URL as-given; ``sse`` → SSE at
    the URL as-given. When it's unknown (None — e.g. a manually-entered URL),
    fall back to suffix heuristics:
    - URL ends with /sse  → ([], url)              SSE only (explicit intent)
    - URL ends with /mcp  → ([url], <base>/sse)    streamable-HTTP, sibling /sse fallback
    - URL has no suffix   → ([url, url/mcp], url/sse)

    The registry gives the canonical endpoint (e.g. Vercel serves streamable-HTTP
    at the root https://mcp.vercel.com), so the bare URL is tried first; /mcp and
    /sse are only invented as heuristic fallbacks when the transport is unknown.
    """
    url = endpoint_url.rstrip("/")

    # Declared transport is authoritative — no probing, no cross-transport fallback.
    # These are the only two values in the MCP ServerJSON remotes[].type enum;
    # anything else falls through to the suffix heuristics below.
    normalized = (transport or "").lower().replace("_", "-")
    if normalized == "streamable-http":
        return [url], None
    if normalized == "sse":
        return [], url

    # Unknown transport → suffix heuristics.
    if url.endswith("/sse"):
        return [], url
    if url.endswith("/mcp"):
        return [url], url[:-4] + "/sse"
    return [url, f"{url}/mcp"], f"{url}/sse"


async def _list_tools(
    endpoint_url: str, headers: dict | None = None, transport: str | None = None
) -> list[dict]:
    """Connect to running MCP server and list tools.

    Transport selection is delegated to :func:`mcp_transport_candidates`; a
    declared ``transport`` is honored exactly (no probing).

    Raises on any connection or protocol error — caller handles retries.
    """
    from mcp import ClientSession

    custom_headers = dict(headers) if headers else None
    timeout_seconds = float(_LIST_TOOLS_ATTEMPT_TIMEOUT)

    streamable_urls, sse_url = mcp_transport_candidates(endpoint_url, transport)

    result = None
    last_streamable_err: BaseException | None = None
    for streamable_url in streamable_urls:
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
            break
        except Exception as transport_err:
            last_streamable_err = transport_err
            logger.debug(
                "Streamable HTTP failed for %s (%s), trying next transport",
                streamable_url,
                transport_err,
            )

    if result is None and sse_url is not None:
        from mcp.client.sse import sse_client

        async with sse_client(
            sse_url,
            timeout=timeout_seconds,
            headers=custom_headers,
        ) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as sess:
                await sess.initialize()
                result = await sess.list_tools()

    if result is None:
        # Declared streamable-http with no SSE fallback and it failed — surface
        # the real transport error rather than a confusing None.
        raise last_streamable_err or RuntimeError(f"No usable MCP transport for {endpoint_url}")

    return [serialize_mcp_tool(t) for t in result.tools]


def _in_progress_is_stale(verification: dict) -> bool:
    """True when an ``in_progress`` verification is old enough to be abandoned.

    verify() releases the row lock before the expensive list_tools work, so an
    interrupted run (deploy/crash/timeout) leaves ``in_progress`` persisted. Any
    live run writes a terminal state within ``_SAFETY_DEADLINE``; an ``in_progress``
    older than that (or with no/invalid timestamp) is stale and must not block a
    re-verify — otherwise the instance is wedged in "verifying" forever.
    """
    at = verification.get("at")
    if not at:
        return True
    try:
        started = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    return (datetime.now(UTC) - started).total_seconds() > _SAFETY_DEADLINE


async def verify(
    instance: MCPServerInstance,
    session=None,
    *,
    extra_headers: dict[str, str] | None = None,
    force: bool = False,
    _list_tools_fn=None,  # test seam
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
        force: Re-run even if the row is already ``in_progress`` (user-initiated
            Verify/Refresh). Prevents a stale in_progress from wedging the row.
        _list_tools_fn: Test seam.

    Returns:
        VerificationPayload with the final status written to the DB.
    """
    if (instance.json_spec or {}).get("type") == "bundle":
        raise NotImplementedError("Bundle verification is derived at read time")

    settings = get_settings()

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

            # If another verify() is genuinely in progress on this row, return its
            # current state — the in-flight caller will write the final result.
            # But NOT when the caller forced a re-run (user clicked Verify), nor
            # when the in_progress is stale (a previous run died before writing a
            # terminal state) — otherwise the row is wedged in "verifying" forever.
            # Terminal states (succeeded/failed) always fall through.
            if (
                locked.verification.get("status") == "in_progress"
                and not force
                and not _in_progress_is_stale(locked.verification)
            ):
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

        # Container-backed verification is an ordinary request through the
        # manager gateway. Go alone decides whether and where to start it.
        if instance_type in ("docker", "command"):
            endpoint_url = settings.mcp.manager_gateway_url(instance_id)
        else:
            endpoint_url = runtime_instance.endpoint_url
        headers = dict(runtime_instance.json_spec.get("headers", {}))
        if extra_headers:
            headers.update(extra_headers)
        # Registry remote servers declare their wire transport; honor it exactly
        # (e.g. Vercel = streamable-http at the root) instead of probing suffixes.
        if instance_type in ("docker", "command"):
            headers.update(settings.mcp.manager_gateway_headers())
            remote_transport = "streamable-http"
        else:
            remote_transport = declared_remote_transport(runtime_instance.json_spec)
        deadline = asyncio.get_event_loop().time() + _SAFETY_DEADLINE
        last_error: BaseException | None = None

        while True:
            try:
                async with asyncio.timeout(_LIST_TOOLS_ATTEMPT_TIMEOUT):
                    if _list_tools_fn is None:
                        tools = await _list_tools(endpoint_url, headers or None, remote_transport)
                    else:
                        tools = await _list_tools_fn(endpoint_url, headers or None)

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
                        "verify: list_tools transient (still provisioning): %s: %s",
                        type(leaf).__name__,
                        leaf,
                        extra={"instance_id": instance_id, "delay": _LIST_TOOLS_RETRY_DELAY},
                    )
                    if asyncio.get_event_loop().time() + _LIST_TOOLS_RETRY_DELAY > deadline:
                        break
                    await asyncio.sleep(_LIST_TOOLS_RETRY_DELAY)
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

        # Deadline exhausted. The gateway already owns runtime health and
        # returns a concrete startup failure when it cannot satisfy demand.
        error_code = "list_tools_timeout"
        error_msg = f"MCP did not become ready within {_SAFETY_DEADLINE}s: {last_error}"

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
