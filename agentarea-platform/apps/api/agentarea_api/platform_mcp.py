"""The platform toolsets served over MCP, and the subset a registered client carries."""

from collections.abc import Collection
from functools import cache
from importlib.metadata import version
from typing import Any, cast

from agentarea_agents_sdk.mcp_server import ToolsetMCPServer, create_mcp_server
from agentarea_common.config.app import get_app_settings
from mcp.types import Icon

INSTRUCTIONS = "AgentArea platform — agents, runs, MCP servers, providers, models, secrets"

DESCRIPTION = (
    "Build, run and govern AI agents on AgentArea: create agents and skills, start and "
    "steer runs, connect MCP servers and OpenAPI tools, wire triggers and event streams, "
    "and manage providers, models, secrets, members and policies across your workspaces."
)

WEBSITE_URL = "https://docs.agentarea.ai"


def server_identity() -> dict[str, Any]:
    """What every AgentArea MCP endpoint reports about itself on ``initialize``."""
    icon = f"{get_app_settings().API_URL.rstrip('/')}/static/icons/agentarea.svg"
    return {
        "title": "AgentArea",
        "description": DESCRIPTION,
        "version": version("agentarea-api"),
        "website_url": WEBSITE_URL,
        "icons": [Icon(src=icon, mime_type="image/svg+xml", sizes=["any"])],
    }


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
        instructions=INSTRUCTIONS,
        workspace_argument=spanning,
        **server_identity(),
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
