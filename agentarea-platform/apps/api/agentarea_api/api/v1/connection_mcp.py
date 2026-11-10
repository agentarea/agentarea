"""An API connection served as an MCP server, at the address every connection has.

``/v1/mcp/{id}/mcp`` reverse-proxies an MCP server instance to its upstream. When
the id names an API (OpenAPI) connection instead, this server answers: each of
the connection's operations is a tool, and each call runs the way an agent's
does, judged by the caller's workspace policy, audited, metered and held for
approval through ``client_mcp.call_openapi_tool``.

The proxy route has already authenticated the caller, bound the connection's
workspace and checked ``use_connection``; it hands the request to this server
with the caller and the connection id, which the handlers read back.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from agentarea_agents_sdk.tools.openapi_tool import _slugify_name
from agentarea_api.api.v1 import client_mcp
from agentarea_api.platform_mcp import server_identity
from agentarea_common.auth.tool_authorization import ToolAuthorizationAction
from agentarea_mcp.application.mcp_aggregator import MCPAggregatorProxy
from mcp.server import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from agentarea_common.auth.context import UserContext
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class _Request:
    user_context: UserContext
    connection_id: UUID


_request_var: ContextVar[_Request | None] = ContextVar("connection_mcp_request", default=None)


def connection_operations(connection) -> dict[str, client_mcp.ClientOpenAPIOperation]:
    """The connection's operations, by the tool name each is served under."""
    operations: dict[str, client_mcp.ClientOpenAPIOperation] = {}
    for tool in connection.available_tools or []:
        operation = tool.get("name")
        if not operation:
            continue
        tool_name = _slugify_name(operation)
        operations[tool_name] = client_mcp.ClientOpenAPIOperation(
            connection_id=str(connection.id),
            connection_name=connection.name,
            operation=operation,
            tool_name=tool_name,
            description=tool.get("description") or "",
            input_schema=tool.get("inputSchema") or {"type": "object", "properties": {}},
        )
    return operations


@asynccontextmanager
async def _connection_service(user_ctx: UserContext) -> AsyncIterator[tuple[AsyncSession, Any]]:
    """A session and an API connection service in the connection's workspace, for one request."""
    from agentarea_common.base.repository_factory import RepositoryFactory
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.config.database import get_database
    from agentarea_secrets.secret_manager_factory import get_real_secret_manager

    from ..deps.services import get_openapi_connection_service

    with workspace_scope(user_ctx.workspace_id):
        async with get_database().session() as session:
            yield (
                session,
                await get_openapi_connection_service(
                    RepositoryFactory(session, user_ctx),
                    get_real_secret_manager(session=session, user_context=user_ctx),
                ),
            )


def _current() -> _Request:
    request = _request_var.get()
    if request is None:
        raise ValueError("No connection on this request")
    return request


async def _list_tools(_ctx: object, _params: PaginatedRequestParams | None) -> ListToolsResult:
    request = _current()
    user_ctx = request.user_context
    async with _connection_service(user_ctx) as (session, service):
        connection = await service.get_connection(request.connection_id)
        if connection is None:
            return ListToolsResult(tools=[])
        operations = connection_operations(connection)
        policy = await client_mcp._effective_tool_policy(session, user_ctx)
    scope = client_mcp.ClientScope(
        proxy=MCPAggregatorProxy(connection.name, "", [], {}, {}),
        skill_registry={},
        platform_tools=frozenset(),
        user_context=user_ctx,
        tool_policy=policy,
        actor_type="client" if user_ctx.client_id else "user",
        openapi=operations,
    )
    # A tool the caller may never run is not offered; one held for approval is.
    return ListToolsResult(
        tools=[
            Tool(name=name, description=operation.description, input_schema=operation.input_schema)
            for name, operation in operations.items()
            if client_mcp._client_tool_decision(scope, name).action
            is not ToolAuthorizationAction.DENY
        ]
    )


async def _call_tool(_ctx: object, params: CallToolRequestParams) -> CallToolResult:
    request = _current()
    async with _connection_service(request.user_context) as (session, service):
        connection = await service.get_connection(request.connection_id)
        if connection is None:
            raise ValueError("Connection not found")
        operation = connection_operations(connection).get(params.name)
        if operation is None:
            return CallToolResult(
                content=[
                    TextContent(type="text", text=f"{connection.name} has no tool {params.name}")
                ],
                is_error=True,
            )
        result = await client_mcp.call_openapi_tool(
            session,
            request.user_context,
            service,
            connection,
            operation.operation,
            params.arguments or {},
        )
    return client_mcp._answer(result)


connection_mcp_server = Server(
    "AgentArea API connection",
    instructions="The operations of one API connection, as tools.",
    **server_identity(),
    on_list_tools=_list_tools,
    on_call_tool=_call_tool,
)

_app: ASGIApp | None = None


def build_app(transport_security: TransportSecuritySettings) -> ASGIApp:
    """Create the server's Streamable HTTP app once, before the lifespan runs its sessions."""
    global _app
    _app = connection_mcp_server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=transport_security,
    )
    return _app


class ConnectionMCPResponse(Response):
    """Hands the proxied request to the connection's MCP server, as the caller."""

    def __init__(self, user_context: UserContext, connection_id: UUID) -> None:
        self._request = _Request(user_context, connection_id)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if _app is None:
            raise RuntimeError("The API connection MCP app was not built at startup")
        token = _request_var.set(self._request)
        try:
            await _app(dict(scope, path="/", raw_path=b"/", root_path=""), receive, send)
        finally:
            _request_var.reset(token)
