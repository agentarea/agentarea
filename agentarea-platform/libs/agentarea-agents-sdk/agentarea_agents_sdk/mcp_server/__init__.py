"""MCP Server adapter — exposes BaseTool/Toolset instances via MCP protocol.

Usage:
    from agentarea_agents_sdk.mcp_server import create_mcp_server

    mcp = create_mcp_server(
        toolsets=[AgentsToolset(), RunsToolset()],
        name="AgentArea",
        workspace_argument=True,
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
from .auth import PROTECTED_RESOURCE_SCOPE_KEY, WORKSPACE_REFERENCE_PATTERN, WORKSPACE_SCOPE_KEY


def create_mcp_server(
    toolsets: list[Toolset | BaseTool],
    name: str = "AgentArea",
    description: str = "",
    *,
    workspace_argument: bool,
) -> FastMCP:
    """Factory: create an MCP server from toolsets/tools.

    Each Toolset is flattened — every @tool_method becomes a separate MCP tool
    named ``{toolset.name}_{method_name}``.  BaseTool instances are registered
    with their own name as-is.

    *workspace_argument* selects how a tool call finds its workspace: True for a
    mount that spans workspaces (each workspace-scoped tool takes a required
    ``workspace``), False for a mount whose URL pins one.
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
    adapter = MCPToolAdapter(server, workspace_argument=workspace_argument)

    for tool in toolsets:
        if isinstance(tool, Toolset):
            adapter.register_toolset(tool)
        elif isinstance(tool, BaseTool):
            if workspace_argument:
                raise TypeError(
                    f"BaseTool {tool.name} cannot be served on a workspace-spanning mount: "
                    "it would run in the caller's default workspace. Wrap it in a Toolset."
                )
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


class PinnedWorkspaceMiddleware:
    """Serve ``{prefix}/{workspace}`` by pinning that workspace on the request.

    Stashes the workspace reference for the auth middleware, names the resource
    for its 401 (each pinned URL is its own RFC 9728 resource), and rewrites the
    path to the mount root so the inner MCP app serves it. A request that names
    no well-formed workspace is answered 404 rather than served unpinned.
    """

    def __init__(self, app: ASGIApp, prefix: str) -> None:
        self.app = app
        self._prefix = prefix.rstrip("/")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith(f"{self._prefix}/"):
            path = path[len(self._prefix) :]
        workspace, _, tail = path.lstrip("/").partition("/")
        if not WORKSPACE_REFERENCE_PATTERN.fullmatch(workspace):
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        scope = dict(scope)
        scope["path"] = f"/{tail}"
        scope[WORKSPACE_SCOPE_KEY] = workspace
        scope[PROTECTED_RESOURCE_SCOPE_KEY] = f"{self._prefix.strip('/')}/{workspace}"
        await self.app(scope, receive, send)


def mount_mcp_app(app: Starlette, path: str, mcp_app: ASGIApp) -> None:
    """Mount an MCP ASGI app so that both ``{path}`` and ``{path}/`` are served."""
    app.mount(path, mcp_app)
    app.add_middleware(_MountRootSlashMiddleware, mount_path=path)
