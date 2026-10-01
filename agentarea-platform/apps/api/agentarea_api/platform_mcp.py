"""The platform toolsets served over MCP, and the subset a registered client carries."""

from collections.abc import Collection
from functools import cache
from typing import cast

from agentarea_agents_sdk.mcp_server import ToolsetMCPServer, create_mcp_server

DESCRIPTION = "AgentArea platform — agents, runs, MCP servers, providers, models, secrets"


def create_platform_mcp_server(*, spanning: bool) -> ToolsetMCPServer:
    """Every platform toolset as one MCP server.

    *spanning* serves all the caller's workspaces: workspace-scoped tools take a
    ``workspace`` argument, and the workspaces toolset finds them. Otherwise the
    request supplies the workspace — a pinned URL, or the client's own.
    """
    from agentarea_agents_sdk.tools.base_tool import BaseTool
    from agentarea_agents_sdk.tools.decorator_tool import Toolset

    # Imported here: the toolsets themselves import this module.
    from .tools import get_platform_tools, get_spanning_mcp_tools

    toolsets = get_spanning_mcp_tools() if spanning else get_platform_tools()
    return create_mcp_server(
        toolsets=cast(list[Toolset | BaseTool], toolsets),
        name="AgentArea",
        description=DESCRIPTION,
        workspace_argument=spanning,
    )


@cache
def client_platform_server() -> ToolsetMCPServer:
    """The server a client's endpoint lists and calls its platform toolsets through.

    Never mounted: ``/mcp/clients/{id}`` calls into it directly, bound to the
    client's workspace and narrowed to the client's attachments.
    """
    return create_platform_mcp_server(spanning=False)


def attachable_toolset(reference: str, disabled_methods: Collection[str]) -> str:
    """Namespace of the platform toolset *reference* names, checking *disabled_methods*.

    Raises ``UnknownToolsetError`` when no toolset a client can carry has that
    name or namespace, or when it has no such method.
    """
    server = client_platform_server()
    server.select({reference: disabled_methods})
    return server.resolve(reference).namespace
