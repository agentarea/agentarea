"""Platform toolsets — expose system capabilities as tools for agents and MCP.

Each Toolset wraps an existing service, creating a per-request service instance
with the correct auth context. Tools are usable both internally (via ToolManager)
and externally (via MCP adapter at /mcp).

User-facing toolsets are exposed by default. Platform-admin toolsets (LLM
provider/model wiring, secret slots, MCP server templates, registries, audit
log, topology, workspace export) are hidden unless ``AGENTAREA_EXPOSE_ADMIN_TOOLS=1``
is set — those are operator concerns, not capabilities most agents should call.
"""

import os

from agentarea_agents_sdk.tools.decorator_tool import Toolset

from .agents_toolset import AgentsToolset
from .audit_toolset import AuditToolset
from .files_toolset import FilesToolset
from .inbox_toolset import InboxToolset
from .mcp_servers_toolset import MCPServersToolset
from .models_toolset import ModelsToolset
from .network_toolset import NetworkToolset
from .openapi_connections_toolset import OpenAPIConnectionsToolset
from .projects_toolset import ProjectsToolset
from .providers_toolset import ProvidersToolset
from .registries_toolset import RegistriesToolset
from .runs_toolset import RunsToolset
from .secrets_toolset import SecretsToolset
from .skills_toolset import SkillsToolset
from .triggers_toolset import TriggersToolset
from .workspace_config_toolset import WorkspaceConfigToolset


def _user_toolsets() -> list[Toolset]:
    """Toolsets useful for everyday agent workflows."""
    return [
        AgentsToolset(),
        RunsToolset(),
        SkillsToolset(),
        ProjectsToolset(),
        TriggersToolset(),
        FilesToolset(),
        InboxToolset(),
        OpenAPIConnectionsToolset(),
    ]


def _admin_toolsets() -> list[Toolset]:
    """Toolsets that manage platform plumbing (providers, models, secrets, MCP
    server templates, registries, audit log, topology, workspace config)."""
    return [
        MCPServersToolset(),
        ProvidersToolset(),
        ModelsToolset(),
        SecretsToolset(),
        RegistriesToolset(),
        AuditToolset(),
        NetworkToolset(),
        WorkspaceConfigToolset(),
    ]


def get_platform_tools() -> list[Toolset]:
    """Collect platform toolsets, excluding admin tools by default.

    Toolsets are stateless — they resolve services per-request using
    the MCP auth ContextVar and the DB session factory.
    """
    tools = _user_toolsets()
    if os.getenv("AGENTAREA_EXPOSE_ADMIN_TOOLS", "").lower() in ("1", "true", "yes"):
        tools.extend(_admin_toolsets())
    return tools
