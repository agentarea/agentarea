"""MCP Server adapter — exposes BaseTool/Toolset instances via MCP protocol.

Usage:
    from agentarea_agents_sdk.mcp_server import create_mcp_server

    mcp = create_mcp_server(
        toolsets=[AgentsToolset(), RunsToolset()],
        name="AgentArea",
    )
    app.mount("/mcp", mcp.streamable_http_app())
"""

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from ..tools.base_tool import BaseTool
from ..tools.decorator_tool import Toolset
from .adapter import MCPToolAdapter


def create_mcp_server(
    toolsets: list[Toolset | BaseTool],
    name: str = "AgentArea",
    description: str = "",
) -> FastMCP:
    """Factory: create an MCP server from toolsets/tools.

    Each Toolset is flattened — every @tool_method becomes a separate MCP tool
    named ``{toolset.name}_{method_name}``.  BaseTool instances are registered
    with their own name as-is.
    """
    # streamable_http_path="/" so the route lives at the mount root.
    # When FastAPI mounts this at /mcp, the endpoint is /mcp (not /mcp/mcp).
    # stateless_http=True because the API runs as several replicas behind an
    # ingress with no session affinity: a session held in one replica's memory
    # is gone the moment the next request lands elsewhere, and the client sees
    # "Session not found" before it can list a single tool.
    # transport_security disabled: FastMCP auto-enables DNS rebinding protection
    # when host is the default 127.0.0.1, but we mount under FastAPI behind a
    # reverse proxy where Host validation should be handled at the ingress layer.
    server = FastMCP(
        name=name,
        instructions=description,
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    adapter = MCPToolAdapter(server)

    for tool in toolsets:
        if isinstance(tool, Toolset):
            adapter.register_toolset(tool)
        elif isinstance(tool, BaseTool):
            adapter.register_tool(tool)
        else:
            raise TypeError(f"Expected Toolset or BaseTool, got {type(tool).__name__}")

    return server


class _MountRootSlashMiddleware:
    """Serve the mount root itself instead of redirecting to its slash form.

    ``app.mount("/mcp", …)`` does not match a request for ``/mcp``; Starlette
    falls through to its redirect_slashes handling and answers 307 ``/mcp/``.
    The resource identifier we advertise carries no trailing slash, so a client
    that binds its token to the URL it ends up posting to and a server that
    validates the audience against the advertised identifier disagree by one
    character. Rewriting before routing removes the hop entirely.
    """

    def __init__(self, app: ASGIApp, mount_path: str) -> None:
        self.app = app
        self._mount_path = mount_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == self._mount_path:
            scope = dict(scope)
            scope["path"] = f"{self._mount_path}/"
            if scope.get("raw_path") is not None:
                scope["raw_path"] = scope["raw_path"] + b"/"
        await self.app(scope, receive, send)


def mount_mcp_app(app: Starlette, path: str, mcp_app: ASGIApp) -> None:
    """Mount an MCP ASGI app so that both ``{path}`` and ``{path}/`` are served."""
    app.mount(path, mcp_app)
    app.add_middleware(_MountRootSlashMiddleware, mount_path=path)
