"""Per-instance MCP reverse proxy (Streamable HTTP only — no SSE transport).

Each MCP instance gets a stable governed endpoint:

    POST/GET/DELETE  /v1/mcp/{instance_id}/mcp

The proxy resolves the instance, determines the upstream URL, injects
outbound auth headers (OAuth2 bearer with auto-refresh, API key, etc.), and
streams the request/response transparently. AgentArea owns access control
(workspace scoping today; access-control next) and audit centrally; downstream MCP
servers see only governed traffic.

Dispatch by instance type:

* ``url``     -> ``server_spec.remote_url`` (e.g. https://mcp.clickup.com/mcp)
* ``docker``/``command`` -> Go manager demand gateway, which owns cold start
* ``compound``-> not yet implemented here; see compound proxy
"""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
from agentarea_api.api.deps.services import (
    BaseSecretManagerDep,
    DatabaseSessionDep,
    MCPServerInstanceServiceDep,
)
from agentarea_common.auth.dependencies import UserContextDep
from agentarea_common.auth.tool_authorization import decide_tool_policy
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
from agentarea_mcp.infrastructure.repository import (
    MCPServerInstanceRepository,
    MCPServerRepository,
)
from agentarea_openapi.application.url_validator import build_pinned_target, validate_url
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

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


def _filter_inbound_headers(headers) -> dict[str, str]:
    """Headers we forward upstream (drop hop-by-hop, host, our own auth)."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP:
            continue
        # Don't forward the user's auth to upstream — we inject our own.
        if lk == "authorization":
            continue
        out[k] = v
    return out


def _filter_outbound_headers(headers) -> dict[str, str]:
    """Headers we forward back to the client (drop hop-by-hop)."""
    out: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out[k] = v
    return out


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


async def _authorize_mcp_tool_calls(body: bytes, user_context, session) -> None:
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
        decision = decide_tool_policy(policy, tool_name)
        if not decision.allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Tool call denied: {tool_name}: {decision.reason}",
            )


async def _resolve_upstream_url(instance, server_spec) -> tuple[str, str | None]:
    """Compute the upstream MCP endpoint URL and the instance type.

    URL-type instances carry their full endpoint URL on the parent server
    spec (remote_url). Container-backed instances expose MCP at ``/mcp`` on
    the resolved internal URL. The returned type drives SSRF handling: only
    ``url`` upstreams are user-controlled and must be validated/pinned.
    """
    json_spec: dict[str, Any] = instance.json_spec or {}
    instance_type = json_spec.get("type") or json_spec.get("server_type")
    if not instance_type and server_spec is not None:
        if getattr(server_spec, "remote_url", None):
            instance_type = "url"
        elif getattr(server_spec, "cmd", None):
            instance_type = "command"
        else:
            instance_type = "docker"

    if instance_type == "url":
        if server_spec is not None and getattr(server_spec, "remote_url", None):
            return server_spec.remote_url, instance_type
        spec_json = getattr(server_spec, "json_spec", None) or {}
        if spec_json.get("type") == "url":
            return spec_json.get("endpoint_url") or spec_json.get("url") or "", instance_type
        return "", instance_type

    if instance_type in ("docker", "command"):
        return get_settings().mcp.manager_gateway_url(instance.id), instance_type
    return "", instance_type


def _guard_and_pin_upstream(
    upstream_url: str, instance_type: str | None, *, allow_private: bool
) -> tuple[str | httpx.URL, str | None, dict | None]:
    """SSRF chokepoint for outbound proxy requests.

    Container/command upstreams are always the manager gateway, an
    operator-configured address this process builds itself, so they pass through
    unchanged. URL-type upstreams are user-controlled, so they are validated
    against private/metadata ranges (unless ``allow_private``) and pinned to the
    resolved IP to defeat DNS rebinding — the Host header and TLS SNI keep the
    original hostname.

    Returns ``(request_target, host_header, extensions)``.

    Raises:
        ValueError: If a URL-type upstream is not safe to fetch.
    """
    if instance_type != "url":
        return upstream_url, None, None

    resolved_ips = validate_url(upstream_url, allow_private=allow_private)
    target = build_pinned_target(upstream_url, resolved_ips[0] if resolved_ips else None)
    request_target = httpx.URL(
        scheme=target.scheme,
        host=target.host,
        port=target.port,
        path=target.path,
        query=target.raw_query,
    )
    extensions = {"sni_hostname": target.original_host} if target.original_host else None
    return request_target, target.original_host, extensions


@router.get(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_get",
)
@router.post(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_post",
)
@router.delete(
    "/{instance_id}/mcp",
    operation_id="proxy_instance_v1_mcp__instance_id__mcp_delete",
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

    # SSRF guard: validate + pin user-controlled URL-type upstreams before any
    # outbound request. Container/command upstreams are internal and pass through.
    allow_private = get_settings().mcp.ALLOW_PRIVATE_URLS
    try:
        request_target, pinned_host, extensions = _guard_and_pin_upstream(
            upstream_url, instance_type, allow_private=allow_private
        )
    except ValueError as exc:
        # Strip CR/LF from the user-controlled path param to prevent log forging.
        safe_instance_id = str(instance_id).replace("\r", "").replace("\n", "")
        logger.warning("Rejected SSRF-unsafe MCP upstream for %s: %s", safe_instance_id, exc)
        raise HTTPException(
            status_code=400, detail=f"Upstream MCP URL is not allowed: {exc}"
        ) from exc

    outbound_headers = _filter_inbound_headers(request.headers)
    if pinned_host:
        # Connect to the pinned IP but present the original hostname upstream.
        outbound_headers.setdefault("Host", pinned_host)
    if instance.auth_config_id:
        auth_repo = MCPAuthConfigRepository(db_session, user_context)
        auth_config = await auth_repo.get_by_id(instance.auth_config_id)
        if auth_config is not None:
            auth_service = MCPAuthService(auth_repo, secret_manager)
            try:
                injected = await auth_service.get_auth_headers(auth_config)
                outbound_headers.update(injected)
            except Exception as exc:
                logger.exception(
                    "Failed to build outbound auth headers for instance %s", instance_id
                )
                raise HTTPException(status_code=502, detail="Upstream auth failed") from exc

    if instance_type in ("docker", "command"):
        try:
            outbound_headers.update(get_settings().mcp.manager_gateway_headers())
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503, detail="MCP demand gateway is not configured"
            ) from exc

    body = await request.body() if request.method in ("POST", "DELETE") else None
    if request.method == "POST" and body is not None:
        await _authorize_mcp_tool_calls(body, user_context, db_session)
    params = dict(request.query_params)

    client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=None, write=30, pool=10))
    try:
        upstream_req = client.build_request(
            request.method,
            request_target,
            content=body,
            params=params,
            headers=outbound_headers,
            extensions=extensions or {},
        )
        upstream_resp = await client.send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("Upstream MCP error for %s: %s", instance_id, exc)
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
