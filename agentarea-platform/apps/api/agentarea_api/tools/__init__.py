"""Platform toolsets — expose workspace-scoped capabilities as tools for agents and MCP.

Each Toolset wraps an existing service, creating a per-request service instance
with the correct auth context. Tools are usable both internally (via ToolManager)
and externally (via MCP adapter at /mcp).

All toolsets here operate on the caller's workspace. System-wide / cross-workspace
operations (registry sync, etc.) are intentionally not exposed as MCP tools and
will live in a separate admin MCP server when needed.
"""

from agentarea_agents_sdk.tools.decorator_tool import Toolset

from .agents_toolset import AgentsToolset
from .audit_toolset import AuditToolset
from .clients_toolset import ClientsToolset
from .files_toolset import FilesToolset
from .inbox_toolset import InboxToolset
from .mcp_servers_toolset import MCPServersToolset
from .members_toolset import MembersToolset
from .models_toolset import ModelsToolset
from .network_toolset import NetworkToolset
from .openapi_connections_toolset import OpenAPIConnectionsToolset
from .policies_toolset import PoliciesToolset
from .projects_toolset import ProjectsToolset
from .providers_toolset import ProvidersToolset
from .runs_toolset import RunsToolset
from .secrets_toolset import SecretsToolset
from .skills_toolset import SkillsToolset
from .triggers_toolset import TriggersToolset
from .workspace_config_toolset import WorkspaceConfigToolset


def get_platform_tools() -> list[Toolset]:
    """Collect platform toolsets — workspace-scoped capabilities.

    Toolsets are stateless — they resolve services per-request using
    the MCP auth ContextVar and the DB session factory.
    """
    return [
        AgentsToolset(),
        RunsToolset(),
        SkillsToolset(),
        ProjectsToolset(),
        ClientsToolset(),
        MembersToolset(),
        PoliciesToolset(),
        TriggersToolset(),
        FilesToolset(),
        InboxToolset(),
        OpenAPIConnectionsToolset(),
        MCPServersToolset(),
        ProvidersToolset(),
        ModelsToolset(),
        SecretsToolset(),
        AuditToolset(),
        NetworkToolset(),
        WorkspaceConfigToolset(),
    ]
