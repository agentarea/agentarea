"""WorkspaceConfigToolset — export workspace configuration as YAML."""

import json

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_read_context


class WorkspaceConfigToolset(Toolset):
    """Export the workspace's agents, MCP instances, and provider configs as YAML."""

    @tool_method
    async def export(self) -> str:
        """Export current workspace configuration as YAML (secrets are placeholders)."""
        async with platform_read_context() as (_session, user_ctx, repo_factory, broker, secret):
            from agentarea_agents.application.agent_service import AgentService
            from agentarea_agents.application.import_export_service import (
                WorkspaceImportExportService,
            )
            from agentarea_agents.application.skill_service import SkillService
            from agentarea_common.auth.authorization import AuthorizationService
            from agentarea_common.di.container import resolve
            from agentarea_llm.application.provider_service import ProviderService
            from agentarea_llm.infrastructure.model_instance_repository import (
                ModelInstanceRepository,
            )
            from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
            from agentarea_llm.infrastructure.provider_config_repository import (
                ProviderConfigRepository,
            )
            from agentarea_llm.infrastructure.provider_spec_repository import (
                ProviderSpecRepository,
            )
            from agentarea_mcp.application.service import MCPServerInstanceService

            authz = resolve(AuthorizationService)
            agent_service = AgentService(
                repo_factory, broker, authorization_service=authz
            )
            mcp_instance_service = MCPServerInstanceService(
                repository_factory=repo_factory,
                event_broker=broker,
                secret_manager=secret,
            )
            provider_service = ProviderService(
                provider_spec_repo=ProviderSpecRepository(_session, user_ctx),
                provider_config_repo=ProviderConfigRepository(_session, user_ctx),
                model_spec_repo=ModelSpecRepository(_session, user_ctx),
                model_instance_repo=ModelInstanceRepository(_session, user_ctx),
                event_broker=broker,
                secret_manager=secret,
            )
            skill_service = SkillService(repository_factory=repo_factory, user_context=user_ctx)
            service = WorkspaceImportExportService(
                agent_service=agent_service,
                repository_factory=repo_factory,
                mcp_instance_service=mcp_instance_service,
                provider_service=provider_service,
                skill_service=skill_service,
            )
            yaml_text = await service.export_workspace()
            return json.dumps({"yaml": yaml_text})
