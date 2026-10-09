"""Per-instance MCP reverse proxy (Streamable HTTP only — no SSE transport).

Each MCP instance gets a stable governed endpoint:

    POST/GET/DELETE  /v1/mcp/{instance_id}/mcp

The proxy resolves the instance, determines the upstream URL, injects the
instance's own headers (secret ones from the secret store) and outbound auth
headers (OAuth2 bearer with auto-refresh, API key, etc.), and
streams the request/response transparently. AgentArea owns access control
(workspace scoping today; access-control next) and audit centrally; downstream MCP
servers see only governed traffic.

Dispatch by instance type:

* ``url``     -> ``server_spec.remote_url`` (e.g. https://mcp.clickup.com/mcp)
* ``docker``/``command`` -> Go manager demand gateway, which owns cold start
* ``compound``-> not yet implemented here; see compound proxy
"""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import httpx
from agentarea_agents_sdk.tools.mcp_tool_identity import mcp_tool_target
from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    DatabaseSessionDep,
    MCPServerInstanceServiceDep,
)
from agentarea_common.auth.dependencies import (
    PrincipalDep,
    UserContextDep,
    bind_request_workspace,
    binds_workspace,
)
from agentarea_common.auth.route_authz import requires
from agentarea_common.auth.tool_authorization import decide_tool_policy
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.config import get_settings
from agentarea_common.config.database import get_read_db_session
from agentarea_common.utils.url_safety import OutboundPolicy, safe_async_client
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.application.mcp_client import (
    GATEWAY_START_WAIT_SECONDS,
    gateway_start_retry_delay,
)
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.transport import CONTAINER_TRANSPORTS, MCPTransport
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_mcp.transport_spec import instance_transport_spec
from agentarea_openapi.application.url_validator import validate_url
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from mcp.shared.inbound import NAME_BEARING_METHODS, decode_header_value
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mcp", tags=["mcp-proxy"])

# Hop-by-hop headers per RFC 7230 §6.1, plus a few that must not be forwarded
# when proxying (host is rewritten by httpx; content-length is recomputed).
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
        "content-length",
    }
)


# The upstream is member-supplied: it receives the MCP protocol headers
# (``Mcp-*`` plus the content negotiation and resume headers the transport uses)
# and nothing else of the caller's -- not cookies, not forwarding headers, not
# the caller's own auth (we inject the instance's).
_FORWARDED_REQUEST_HEADERS = frozenset({"accept", "content-type", "last-event-id"})


def _filter_inbound_headers(headers) -> dict[str, str]:
    """The MCP protocol headers of the caller's request, for the upstream."""
    return {
        k: v
        for k, v in headers.items()
        if k.lower() in _FORWARDED_REQUEST_HEADERS or k.lower().startswith("mcp-")
    }


def _filter_outbound_headers(headers) -> dict[str, str]:
    """Upstream response headers for the client, minus hop-by-hop and cookies.

    An upstream's ``Set-Cookie`` would be replayed on the API origin.
    """
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP or lk == "set-cookie":
            continue
        out[k] = v
    return out


class _MCPHeaderMismatchError(Exception):
    """A request envelope header disagrees with the JSON-RPC body."""

    def __init__(self, request_id: Any, message: str) -> None:
        self.body = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32020, "message": message},
        }
        super().__init__(message)


def _mcp_header_value(headers, name: str) -> str | None:
    for header_name, value in headers.items():
        if header_name.lower() == name.lower():
            return value
    return None


def _validate_mcp_header_consistency(payload: Any, headers) -> None:
    """Reject routing headers that disagree with a single JSON-RPC body."""
    if headers is None:
        return

    method_header = _mcp_header_value(headers, "Mcp-Method")
    name_header = _mcp_header_value(headers, "Mcp-Name")
    if method_header is None and name_header is None:
        # A 2025-era request: no routing headers to hold to the body.
        return

    if isinstance(payload, list):
        raise _MCPHeaderMismatchError(
            None,
            "Header mismatch: Mcp-Method and Mcp-Name headers cannot be "
            "validated against a JSON-RPC batch body",
        )

    if not isinstance(payload, dict):
        raise _MCPHeaderMismatchError(
            None,
            "Header mismatch: routing headers require a JSON-RPC request object",
        )

    request_id = payload.get("id")
    body_method = payload.get("method")
    if method_header is not None and method_header != body_method:
        raise _MCPHeaderMismatchError(
            request_id,
            f"Header mismatch: Mcp-Method header value {method_header!r} "
            f"does not match body value {body_method!r}",
        )

    if name_header is None:
        return
    name_key = NAME_BEARING_METHODS.get(body_method) if isinstance(body_method, str) else None
    if name_key is None:
        raise _MCPHeaderMismatchError(
            request_id,
            f"Header mismatch: Mcp-Name header is not defined for request method {body_method!r}",
        )
    raw_params = payload.get("params")
    params = raw_params if isinstance(raw_params, dict) else {}
    body_name = params.get(name_key)
    decoded_name = decode_header_value(name_header)
    if decoded_name is None or decoded_name != body_name:
        raise _MCPHeaderMismatchError(
            request_id,
            f"Header mismatch: Mcp-Name header value {name_header!r} "
            f"does not match body value {body_name!r}",
        )


def _iter_jsonrpc_tool_calls(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    """Extract MCP JSON-RPC tool calls from a request payload."""
    messages = payload if isinstance(payload, list) else [payload]
    calls: list[tuple[str, dict[str, Any]]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("method") != "tools/call":
            continue
        raw_params = message.get("params")
        params = raw_params if isinstance(raw_params, dict) else {}
        tool_name = params.get("name")
        if not isinstance(tool_name, str) or not tool_name:
            continue
        arguments = params.get("arguments")
        calls.append((tool_name, arguments if isinstance(arguments, dict) else {}))
    return calls


async def authorize_mcp_tool_call(
    tool_name: str,
    user_context,
    session,
    *,
    instance_id: UUID,
    policy: dict[str, Any] | None = None,
) -> None:
    """Deny one MCP tool call when the workspace policy does not permit it.

    ``tool_name`` is the raw name the server advertises; a rule may also name the
    tool through its server as ``mcp:<instance id>:<tool>``.
    """
    if policy is None:
        resolver = GovernancePolicyResolver(RepositoryFactory(session, user_context))
        snapshot = await resolver.resolve(
            workspace_id=user_context.workspace_id,
            user_id=user_context.user_id,
        )
        policy = snapshot.to_json_dict()

    decision = decide_tool_policy(
        policy, tool_name, aliases=(mcp_tool_target(str(instance_id), tool_name),)
    )
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Tool call denied: {tool_name}: {decision.reason}",
        )


async def _authorize_mcp_tool_calls(
    body: bytes,
    user_context,
    session,
    *,
    instance_id: UUID,
    headers=None,
) -> None:
    """Deny JSON-RPC tool calls the governance policy does not permit.

    The proxy has no task snapshot, so it resolves the workspace+user policy at
    request time and runs the same PDP (``decide_tool_policy``) the disclosure,
    workflow gate, and tool activity use — one authorization vocabulary across
    every tool path. Resolving here (outside the Temporal sandbox) is fine.
    """
    if not body:
        return
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return
    _validate_mcp_header_consistency(payload, headers)
    tool_calls = _iter_jsonrpc_tool_calls(payload)
    if not tool_calls:
        return

    resolver = GovernancePolicyResolver(RepositoryFactory(session, user_context))
    snapshot = await resolver.resolve(
        workspace_id=user_context.workspace_id,
        user_id=user_context.user_id,
    )
    policy = snapshot.to_json_dict()

    for tool_name, _tool_args in tool_calls:
        await authorize_mcp_tool_call(
            tool_name,
            user_context,
            session,
            instance_id=instance_id,
            policy=policy,
        )


async def _resolve_upstream_url(instance, server_spec) -> tuple[str, MCPTransport]:
    """Compute the upstream MCP endpoint URL and the instance's transport.

    URL-type instances connect to the endpoint their server spec declares.
    Container-backed instances go through the manager gateway. The transport
    drives SSRF handling: only ``url`` upstreams are user-controlled and must be
    validated/pinned.
    """
    transport = MCPTransport(instance.transport)
    if transport == MCPTransport.URL:
        if server_spec is None:
            return "", transport
        return instance_transport_spec(server_spec, instance).get("endpoint_url") or "", transport
    if transport in CONTAINER_TRANSPORTS:
        return get_settings().mcp.manager_gateway_url(instance.id), transport
    return "", transport


def _guard_upstream(
    upstream_url: str, instance_type: MCPTransport, *, policy: OutboundPolicy
) -> None:
    """SSRF pre-check for outbound proxy requests.

    Container/command upstreams are always the manager gateway, an
    operator-configured address this process builds itself, so they pass
    unchecked. URL-type upstreams are user-controlled, so they are validated
    against private/metadata ranges (unless ``policy`` admits them) and answered
    with a 400 here; ``_upstream_client`` vets the address it dials again.

    Raises:
        ValueError: If a URL-type upstream is not safe to fetch.
    """
    if instance_type == MCPTransport.URL:
        validate_url(upstream_url, policy=policy)


def _upstream_client(instance_type: MCPTransport, *, policy: OutboundPolicy) -> httpx.AsyncClient:
    """The client for this upstream: the pinned one for a member's URL.

    It resolves, vets and pins the address for each request, so a name cannot
    rebind between the check and the connection, and hands a proxied request to
    the proxy by name.
    """
    timeout = httpx.Timeout(connect=10, read=None, write=30, pool=10)
    if instance_type == MCPTransport.URL:
        return safe_async_client(policy=policy, timeout=timeout)
    return httpx.AsyncClient(timeout=timeout)


@binds_workspace
async def bind_mcp_instance_workspace(
    request: Request,
    instance_id: str,
    principal: PrincipalDep,
    db_session: AsyncSession = Depends(get_read_db_session, scope="function"),
) -> None:
    """Act in the workspace of the instance the URL names.

    The endpoint is addressed by instance id alone, so the instance is located
    across workspaces and the caller must reach the one it lives in. A foreign
    or malformed id answers like a missing instance. The id is parsed here, not
    by FastAPI: a validation error in a dependency does not stop the ones after
    it, which would then find no workspace bound and fail as a server error.
    """
    try:
        instance_uuid = UUID(instance_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="MCP instance not found") from None
    with unscoped("the proxy URL names an instance; its workspace is the one to bind"):
        located = await db_session.execute(
            select(MCPServerInstance.workspace_id).where(MCPServerInstance.id == instance_uuid)
        )
    workspace_id = located.scalar_one_or_none()
    if workspace_id is None or str(workspace_id) not in (principal.accessible_workspaces or []):
        raise HTTPException(status_code=404, detail="MCP instance not found")
    bind_request_workspace(request, str(workspace_id), await workspace_slug_for(str(workspace_id)))


@router.get(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_get",
    dependencies=[requires("use", "mcp_instance", id_param="instance_id")],
)
@router.post(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_post",
    dependencies=[requires("use", "mcp_instance", id_param="instance_id")],
)
@router.delete(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_delete",
    dependencies=[requires("use", "mcp_instance", id_param="instance_id")],
)
async def proxy_instance(
    instance_id: UUID,
    request: Request,
    user_context: UserContextDep,
    db_session: DatabaseSessionDep,
    secret_manager: BaseSecretManagerDep,
    instance_service: MCPServerInstanceServiceDep,
):
    """Reverse-proxy MCP Streamable HTTP traffic to the instance's upstream."""
    instance_repo = MCPServerInstanceRepository(db_session, user_context)
    instance = await instance_repo.get_by_id(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="MCP instance not found")

    server_spec = None
    if instance.server_spec_id:
        server_repo = MCPServerRepository(db_session, user_context)
        server_spec = await server_repo.get_server_by_id(instance.server_spec_id)

    upstream_url, instance_type = await _resolve_upstream_url(instance, server_spec)
    if not upstream_url:
        raise HTTPException(
            status_code=400,
            detail="Instance has no resolvable upstream MCP URL",
        )

    # SSRF guard: validate user-controlled URL-type upstreams before any outbound
    # request. Container/command upstreams are internal and pass through.
    policy = OutboundPolicy.from_env()
    try:
        _guard_upstream(upstream_url, instance_type, policy=policy)
    except ValueError as exc:
        # Strip CR/LF from the user-controlled path param to prevent log forging.
        safe_instance_id = str(instance_id).replace("\r", "").replace("\n", "")
        logger.warning(
            "Rejected SSRF-unsafe MCP upstream for %s: %s", safe_instance_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=400, detail=f"Upstream MCP URL is not allowed: {exc}"
        ) from exc

    outbound_headers = _filter_inbound_headers(request.headers)
    try:
        outbound_headers.update(await instance_service.outbound_headers(instance))
    except Exception as exc:
        logger.exception("Failed to build outbound headers for instance %s", instance_id)
        raise HTTPException(status_code=502, detail="Upstream auth failed") from exc
    if instance.auth_config_id:
        auth_repo = MCPAuthConfigRepository(db_session, user_context)
        auth_config = await auth_repo.get_by_id(instance.auth_config_id)
        if auth_config is not None:
            auth_service = MCPAuthService(auth_repo, secret_manager)
            try:
                injected = await auth_service.get_auth_headers_for(auth_config, upstream_url)
                outbound_headers.update(injected)
            except Exception as exc:
                logger.exception(
                    "Failed to build outbound auth headers for instance %s", instance_id
                )
                raise HTTPException(status_code=502, detail="Upstream auth failed") from exc

    if instance_type in CONTAINER_TRANSPORTS:
        try:
            outbound_headers.update(get_settings().mcp.manager_gateway_headers())
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503, detail="MCP demand gateway is not configured"
            ) from exc

    body = await request.body() if request.method in ("POST", "DELETE") else None
    if request.method == "POST" and body is not None:
        try:
            await _authorize_mcp_tool_calls(
                body,
                user_context,
                db_session,
                instance_id=instance.id,
                headers=request.headers,
            )
        except _MCPHeaderMismatchError as exc:
            return JSONResponse(status_code=400, content=exc.body)
    params = dict(request.query_params)

    client = _upstream_client(instance_type, policy=policy)
    try:
        upstream_req = client.build_request(
            request.method,
            upstream_url,
            content=body,
            params=params,
            headers=outbound_headers,
        )
        upstream_resp = await client.send(upstream_req, stream=True)
        if instance_type in CONTAINER_TRANSPORTS:
            upstream_resp = await _wait_out_gateway_start(
                client, upstream_req, upstream_resp, request
            )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("Upstream MCP error for %s: %s", instance_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Upstream MCP error: {exc}") from exc

    async def _iter():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()
            await client.aclose()

    return StreamingResponse(
        _iter(),
        status_code=upstream_resp.status_code,
        headers=_filter_outbound_headers(upstream_resp.headers),
        media_type=upstream_resp.headers.get("content-type"),
    )


async def _wait_out_gateway_start(
    client: httpx.AsyncClient,
    upstream_req: httpx.Request,
    upstream_resp: httpx.Response,
    request: Request,
) -> httpx.Response:
    """Repeat a request the gateway answered "workload is starting".

    The gateway brings a reclaimed workload up for the request that asked first
    and turns concurrent ones away without forwarding them. Waiting here gives
    every client the workload that start produces, not only clients that know
    the gateway's header. Stops when the client has gone.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + GATEWAY_START_WAIT_SECONDS
    while True:
        delay = gateway_start_retry_delay(upstream_resp.status_code, upstream_resp.headers)
        if delay is None or loop.time() + delay > deadline or await request.is_disconnected():
            return upstream_resp
        await upstream_resp.aclose()
        await asyncio.sleep(delay)
        upstream_resp = await client.send(upstream_req, stream=True)
