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
    server = FastMCP(name=name, instructions=description, streamable_http_path="/", stateless_http=True)
    adapter = MCPToolAdapter(server)

    for tool in toolsets:
        if isinstance(tool, Toolset):
            adapter.register_toolset(tool)
        elif isinstance(tool, BaseTool):
            adapter.register_tool(tool)
        else:
            raise TypeError(f"Expected Toolset or BaseTool, got {type(tool).__name__}")

    return server
