"""Dynamically-scoped MCP endpoint for clients (agent-proxies).

A single MCP server is mounted at ``/client-mcp`` and its session manager is
started once in the app lifespan. Each request carries a client id in the path
(``/client-mcp/{client_id}``); a scope middleware stashes it in a ContextVar and
the ``list_tools`` / ``call_tool`` handlers resolve that client's effective MCP
instance set (its own attachments unioned with those of its source project) and
aggregate the member tools on the fly.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

from agentarea_agents_sdk.mcp_server.auth import PROTECTED_RESOURCE_SCOPE_KEY
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from agentarea_mcp.application.tool_list_cache import RedisToolListCache
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent, Tool
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

_client_id_var: ContextVar[str | None] = ContextVar("client_mcp_client_id", default=None)


class ClientAccessDeniedError(Exception):
    """Raised when the authenticated principal lacks `use` on the target client."""


async def _authorize_client_access(user_ctx, client_id: str) -> None:
    """Enforce that the authenticated principal may use this client's bundle.

    A client-credentials principal (token subject IS the client) is trusted for
    its own bundle; any other principal must hold the `use` relation in the
    access-control graph. Raises ``ClientAccessDeniedError`` otherwise.
    """
    if getattr(user_ctx, "client_id", None) == client_id:
        return
    from agentarea_common.auth.permission import PermissionService
    from agentarea_common.di.container import resolve

    allowed = await resolve(PermissionService).check(user_ctx.user_id, "use", "client", client_id)
    if not allowed:
        raise ClientAccessDeniedError(client_id)


client_mcp_server = FastMCP(
    name="AgentArea Client",
    instructions="Scoped tool bundle for a registered client (agent-proxy).",
    streamable_http_path="/",
    stateless_http=True,
    # Same opt-out as the platform ``/mcp`` mount (see ``create_mcp_server``):
    # FastMCP enables DNS-rebinding protection by default with an empty
    # ``allowed_hosts``, so every Host header is answered with 421. We run behind
    # an ingress that owns Host validation, and without this an authenticated
    # harness gets 421 on every call after finishing its OAuth flow.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


_tool_list_cache: RedisToolListCache | None = None


def _tool_cache() -> RedisToolListCache:
    """Process-wide cache handle (the client itself pools connections)."""
    global _tool_list_cache
    if _tool_list_cache is None:
        from agentarea_common.config import get_settings

        _tool_list_cache = RedisToolListCache(get_settings().broker.REDIS_URL)
    return _tool_list_cache


async def _resolve_client_scope(
    client_id: str,
) -> tuple[MCPAggregatorProxy | None, dict]:
    """Resolve a client's MCP instance proxy and skill registry.

    The set is exactly the client's own attachments. Returns
    ``(proxy, skill_registry)``; proxy is None only when the client does not
    exist.
    """
    from agentarea_agents_sdk.skills.skill_catalog_builder import SkillEntry
    from agentarea_api.tools.base import platform_read_context
    from agentarea_mcp.application.service import MCPServerInstanceService
    from agentarea_mcp.infrastructure.client_repository import ClientRepository

    async with platform_read_context() as (session, user_ctx, repo_factory, broker, secret):
        client_repo = ClientRepository(session, user_ctx)
        client = await client_repo.get_by_id(client_id)
        if client is None:
            return None, {}

        await _authorize_client_access(user_ctx, client_id)

        namespaces = await client_repo.get_instance_namespaces(client_id)
        instances = {str(i.id): i for i in client.mcp_instances}
        skills = {str(s.id): s for s in client.skills}

        skill_registry = {
            s.name: SkillEntry(
                name=s.name,
                description=s.description or "",
                content=s.content or "",
                files=[],
            )
            for s in skills.values()
        }

        instance_service = MCPServerInstanceService(repo_factory, broker, secret)
        members: list[AggregatedMember] = []
        instance_urls: dict[str, str] = {}
        instance_names: dict[str, str] = {}
        instance_headers: dict[str, dict[str, str]] = {}
        instance_transports: dict[str, str | None] = {}
        for order, (iid, inst) in enumerate(instances.items()):
            full = await instance_service.repository.get_by_id(inst.id)
            if full is None:
                continue
            try:
                url, headers, transport = await instance_service._resolve_mcp_url_and_headers(full)
            except Exception:
                logger.exception("Failed to resolve MCP url for instance %s", iid)
                continue
            instance_urls[iid] = url
            instance_names[iid] = full.name
            instance_transports[iid] = transport
            if headers:
                instance_headers[iid] = headers
            members.append(
                AggregatedMember(
                    mcp_instance_id=iid,
                    order=order,
                    namespace_prefix=namespaces.get(iid),
                    transport=instance_transports[iid],
                )
            )
        proxy = MCPAggregatorProxy(
            client.name,
            client.description or "",
            members,
            instance_urls,
            instance_names,
            instance_headers,
            tool_cache=_tool_cache(),
        )
        return proxy, skill_registry


def _activate_skill_tool(skill_registry: dict) -> Tool:
    return Tool(
        name="activate_skill",
        description="Load full instructions for an available skill by name.",
        inputSchema={
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": list(skill_registry.keys()),
                    "description": "Name of the skill to activate.",
                }
            },
            "required": ["skill_name"],
        },
    )


@client_mcp_server._mcp_server.list_tools()
async def _list_tools() -> list[Tool]:
    client_id = _client_id_var.get()
    if not client_id:
        return []
    try:
        proxy, skill_registry = await _resolve_client_scope(client_id)
    except ClientAccessDeniedError:
        raise ValueError("Not authorized for this client") from None
    if proxy is None:
        return []
    tools = [
        Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"])
        for t in await proxy.list_namespaced_tools()
    ]
    if skill_registry:
        tools.append(_activate_skill_tool(skill_registry))
    return tools


@client_mcp_server._mcp_server.call_tool()
async def _call_tool(name: str, arguments: dict) -> list[TextContent]:
    client_id = _client_id_var.get()
    if not client_id:
        raise ValueError("No client scope on request")
    try:
        proxy, skill_registry = await _resolve_client_scope(client_id)
    except ClientAccessDeniedError:
        raise ValueError("Not authorized for this client") from None
    if proxy is None:
        raise ValueError("Client not found")

    if name == "activate_skill":
        from agentarea_agents_sdk.skills.skill_toolset import SkillActivationTool

        skill_name = (arguments or {}).get("skill_name", "")
        result = SkillActivationTool(skill_registry).activate_skill(skill_name)
    else:
        result = await proxy.call_namespaced_tool(name, arguments or {})
    text = result if isinstance(result, str) else str(result)
    return [TextContent(type="text", text=text)]


class ClientMCPScopeMiddleware:
    """Extracts the client id from ``/client-mcp/{client_id}`` and rewrites the
    path to the mount root so the inner MCP app serves it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith("/client-mcp/"):
            path = path[len("/client-mcp") :]
        client_id: str | None = None
        if path.startswith("/"):
            client_id, _, tail = path[1:].partition("/")
            client_id = client_id or None
            scope = dict(scope)
            scope["path"] = f"/{tail}" if tail else "/"
            if client_id:
                # Name the resource for the auth middleware's 401: each client's
                # endpoint is its own RFC 9728 resource, and a harness rejects
                # metadata whose `resource` does not match the URL it called.
                scope[PROTECTED_RESOURCE_SCOPE_KEY] = f"client-mcp/{client_id}"
        token = _client_id_var.set(client_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _client_id_var.reset(token)
