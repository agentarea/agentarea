"""Service for importing and exporting workspace configurations."""

import yaml
from typing import Dict, List, Any, Optional
from uuid import UUID

from agentarea_common.base import RepositoryFactory
from agentarea_agents.domain.models import Agent
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.schemas.import_export import (
    WorkspaceConfigYAML,
    AgentYAML,
    MCPInstanceYAML,
    ProviderConfigYAML,
    ImportOptions,
    ImportResult,
)
from pydantic import ValidationError


class WorkspaceImportExportService:
    """Service for importing and exporting workspace configurations."""

    def __init__(
        self,
        agent_service: AgentService,
        repository_factory: RepositoryFactory,
    ):
        self.agent_service = agent_service
        self.repository_factory = repository_factory

    async def export_workspace(self) -> str:
        """Export current workspace configuration to YAML format.

        Returns:
            YAML string containing workspace configuration
        """
        # Get all workspace-scoped resources (exclude system resources)
        agents = await self.agent_service.list()

        # Filter out system agents
        workspace_agents = [agent for agent in agents if agent.workspace_id != "system"]

        # Convert to YAML schemas
        agents_yaml = []
        for agent in workspace_agents:
            agent_dict = {
                "name": agent.name,
                "description": agent.description or "",
                "instruction": agent.instruction or "",
            }

            # Add tools_config if present
            if agent.tools_config:
                agent_dict["tools_config"] = self._sanitize_tools_config(
                    agent.tools_config
                )

            agents_yaml.append(agent_dict)

        # TODO: Export MCP instances (requires MCP service integration)
        mcp_instances_yaml = []

        # TODO: Export provider configs (requires LLM service integration)
        provider_configs_yaml = []

        # Create workspace config
        workspace_config = {
            "agents": agents_yaml,
            "mcp_instances": mcp_instances_yaml,
            "provider_configs": provider_configs_yaml,
        }

        # Convert to YAML
        yaml_str = yaml.dump(
            workspace_config,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        return yaml_str

    async def import_workspace(
        self,
        yaml_content: str,
        options: Optional[ImportOptions] = None,
    ) -> ImportResult:
        """Import workspace configuration from YAML.

        Args:
            yaml_content: YAML string containing workspace configuration
            options: Import options (override, skip missing, etc.)

        Returns:
            ImportResult with counts and error messages
        """
        if options is None:
            options = ImportOptions()

        result = ImportResult(success=False)

        try:
            # Parse YAML
            yaml_data = yaml.safe_load(yaml_content)

            # Validate against schema
            try:
                config = WorkspaceConfigYAML(**yaml_data)
            except ValidationError as e:
                result.errors.append(f"YAML validation error: {e}")
                return result

            # Phase 1: Validate all dependencies
            validation_errors = await self._validate_dependencies(config)
            if validation_errors and not options.skip_missing_dependencies:
                result.errors.extend(validation_errors)
                return result

            if validation_errors:
                result.warnings.extend(validation_errors)

            # Phase 2: Import resources (agents only for now)
            for agent_yaml in config.agents:
                try:
                    await self._import_agent(agent_yaml, options)
                    result.created_agents += 1
                except Exception as e:
                    if not options.skip_missing_dependencies:
                        raise
                    result.warnings.append(
                        f"Failed to import agent '{agent_yaml.name}': {e}"
                    )

            # TODO: Import MCP instances
            # TODO: Import provider configs

            result.success = True
            return result

        except Exception as e:
            result.errors.append(f"Import failed: {str(e)}")
            return result

    async def _validate_dependencies(
        self, config: WorkspaceConfigYAML
    ) -> List[str]:
        """Validate that all referenced resources exist.

        Returns:
            List of validation error messages
        """
        errors = []

        # Validate builtin tools
        from agentarea_agents_sdk.tools.tool_manager import get_available_builtin_tools

        available_tools = get_available_builtin_tools()

        for agent in config.agents:
            if not agent.tools_config or not agent.tools_config.builtin_tools:
                continue

            for tool_config in agent.tools_config.builtin_tools:
                if tool_config.tool_name not in available_tools:
                    errors.append(
                        f"Agent '{agent.name}': Unknown builtin tool "
                        f"'{tool_config.tool_name}'. Available tools: "
                        f"{list(available_tools.keys())}"
                    )

        # TODO: Validate MCP server specs exist
        # TODO: Validate provider specs exist

        return errors

    async def _import_agent(
        self, agent_yaml: AgentYAML, options: ImportOptions
    ) -> Agent:
        """Import a single agent from YAML."""

        # Check if agent with same name exists
        existing_agents = await self.agent_service.list()
        existing_agent = next(
            (a for a in existing_agents if a.name == agent_yaml.name),
            None,
        )

        if existing_agent and not options.override_existing:
            raise ValueError(
                f"Agent '{agent_yaml.name}' already exists. "
                "Use override_existing=true to replace."
            )

        # Convert tools_config to dict
        tools_config_dict = None
        if agent_yaml.tools_config:
            tools_config_dict = agent_yaml.tools_config.model_dump(exclude_none=True)

        # Create or update agent
        if existing_agent and options.override_existing:
            # Update existing
            updated_agent = await self.agent_service.update_agent(
                id=existing_agent.id,
                name=agent_yaml.name,
                description=agent_yaml.description,
                tools_config=tools_config_dict,
            )
            return updated_agent
        else:
            # Create new (without model_id as per requirements)
            new_agent = await self.agent_service.create_agent(
                name=agent_yaml.name,
                description=agent_yaml.description,
                instruction=agent_yaml.instruction,
                model_id=None,  # Explicitly None as per requirements
                tools_config=tools_config_dict,
                events_config=None,  # No events for imported agents
                planning=(
                    agent_yaml.tools_config.planning if agent_yaml.tools_config else False
                ),
            )
            return new_agent

    def _sanitize_tools_config(self, tools_config: Dict[str, Any]) -> Dict[str, Any]:
        """Remove sensitive data from tools_config for export."""
        # Create a deep copy to avoid modifying original
        import copy

        sanitized = copy.deepcopy(tools_config)

        # Remove any API keys or secrets from MCP configs
        if "mcp_server_configs" in sanitized:
            for mcp_config in sanitized["mcp_server_configs"]:
                # Keep structure but mark secrets as placeholders
                if "env_vars" in mcp_config:
                    mcp_config["env_vars"] = {
                        key: "<SECRET_PLACEHOLDER>"
                        for key in mcp_config["env_vars"].keys()
                    }

        return sanitized
