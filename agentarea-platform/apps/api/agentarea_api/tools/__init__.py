"""Platform toolsets — expose system capabilities as tools for agents and MCP.

Each Toolset wraps an existing service, creating a per-request service instance
with the correct auth context. Tools are usable both internally (via ToolManager)
and externally (via MCP adapter at /mcp).
"""

from agentarea_agents_sdk.tools.decorator_tool import Toolset

from .agents_toolset import AgentsToolset
from .mcp_servers_toolset import MCPServersToolset
from .models_toolset import ModelsToolset
from .providers_toolset import ProvidersToolset
from .runs_toolset import RunsToolset
from .secrets_toolset import SecretsToolset


def get_platform_tools() -> list[Toolset]:
    """Collect all platform toolsets.

    Toolsets are stateless — they resolve services per-request using
    the MCP auth ContextVar and the DB session factory.
    """
    return [
        AgentsToolset(),
        RunsToolset(),
        MCPServersToolset(),
        ProvidersToolset(),
        ModelsToolset(),
        SecretsToolset(),
    ]
