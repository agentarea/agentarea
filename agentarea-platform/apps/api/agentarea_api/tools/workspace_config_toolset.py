"""WorkspaceConfigToolset — export workspace configuration as YAML."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_authz import requires_workspace_admin
from agentarea_agents_sdk.tools.tool_definition import toolset
from pydantic import BaseModel, Field

from .base import platform_read_context


class WorkspaceConfigExport(BaseModel):
    yaml: str = Field(
        description="The workspace bundle as YAML: agents, MCP instances, skills and triggers."
    )


@toolset(
    namespace="agentarea/workspace_config",
    display_name="Workspace Config",
    description="Export workspace configuration as YAML.",
    category="platform",
    plane="build",
)
class WorkspaceConfigToolset(Toolset):
    """Export a canonical bundle of agents, MCPs, skills, and supported triggers as YAML."""

    open_world = False

    @tool_method(
        display_name="Export workspace config", effect="read", output=WorkspaceConfigExport
    )
    @requires_workspace_admin()
    async def export(self) -> str:
        """Export a canonical importable workspace bundle as YAML."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, broker, secret):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_agents.application.skill_service import SkillService
            from agentarea_agents.application.workspace_export_service import (
                WorkspaceExportService,
            )
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve
            from agentarea_mcp.application.service import MCPServerInstanceService
            from agentarea_triggers.infrastructure.repository import TriggerRepository

            authz = resolve(AuthorizationService)
            agent_service = AgentService(repo_factory, broker, authorization_service=authz)
            mcp_instance_service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=broker,
                secret_manager=secret,
            )
            skill_service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            service = WorkspaceExportService(
                agent_service=agent_service,
                repository_factory=repo_factory,
                mcp_instance_service=mcp_instance_service,
                skill_service=skill_service,
                trigger_repository=repo_factory.create_repository(TriggerRepository),
            )
            yaml_text = await service.export_workspace()
            return json.dumps({"yaml": yaml_text})
