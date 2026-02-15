"""Service for importing and exporting workspace configurations."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import yaml
from agentarea_common.base import RepositoryFactory
from pydantic import ValidationError

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent
from agentarea_agents.schemas.import_export import (
    AgentYAML,
    ImportOptions,
    ImportResult,
    MCPInstanceYAML,
    ProviderConfigYAML,
    SkillYAML,
    WorkspaceConfigYAML,
)

if TYPE_CHECKING:
    from agentarea_agents.application.skill_service import SkillService
    from agentarea_agents.domain.skill_models import Skill

logger = logging.getLogger(__name__)


class WorkspaceImportExportService:
    """Service for importing and exporting workspace configurations."""

    def __init__(
        self,
        agent_service: AgentService,
        repository_factory: RepositoryFactory,
        mcp_instance_service: Any | None = None,
        provider_service: Any | None = None,
        skill_service: "SkillService | None" = None,
    ):
        self.agent_service = agent_service
        self.repository_factory = repository_factory
        self.mcp_instance_service = mcp_instance_service
        self.provider_service = provider_service
        self.skill_service = skill_service

    async def export_workspace(self) -> str:
        """Export current workspace configuration to YAML format.

        Returns:
            YAML string containing workspace configuration
        """
        # Export skills
        skills_yaml = await self._export_skills()

        # Build skill name lookup for agent export
        skill_id_to_name: dict[str, str] = {}
        if self.skill_service:
            try:
                skills = await self.skill_service.list()
                skill_id_to_name = {str(s.id): s.name for s in skills}
            except Exception as e:
                logger.warning(f"Failed to build skill lookup: {e}")

        # Get all workspace-scoped resources (exclude system resources)
        agents = await self.agent_service.list()

        # Filter out system agents
        workspace_agents = [agent for agent in agents if agent.workspace_id != "system"]

        # Convert to YAML schemas
        agents_yaml: list[dict[str, Any]] = []
        for agent in workspace_agents:
            agent_dict: dict[str, Any] = {
                "name": agent.name,
                "description": agent.description or "",
                "instruction": agent.instruction or "",
            }

            # Add tools if present
            if agent.tools:
                agent_dict["tools"] = agent.tools  # Already in correct list format

            # Add planning if present
            if agent.planning is not None:
                agent_dict["planning"] = agent.planning

            # Add skill_names if agent has skills
            if hasattr(agent, "skills") and agent.skills:
                skill_names = [
                    skill_id_to_name.get(str(s.id), s.name)
                    for s in agent.skills
                    if str(s.id) in skill_id_to_name or hasattr(s, "name")
                ]
                if skill_names:
                    agent_dict["skill_names"] = skill_names

            agents_yaml.append(agent_dict)

        # Export MCP instances
        mcp_instances_yaml = await self._export_mcp_instances()

        # Export provider configs
        provider_configs_yaml = await self._export_provider_configs()

        # Create workspace config
        workspace_config: dict[str, Any] = {}

        # Only include non-empty sections
        if skills_yaml:
            workspace_config["skills"] = skills_yaml
        if agents_yaml:
            workspace_config["agents"] = agents_yaml
        if mcp_instances_yaml:
            workspace_config["mcp_instances"] = mcp_instances_yaml
        if provider_configs_yaml:
            workspace_config["provider_configs"] = provider_configs_yaml

        # Convert to YAML
        yaml_str = yaml.dump(
            workspace_config,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

        return yaml_str

    async def _export_mcp_instances(self) -> list[dict]:
        """Export MCP server instances from the current workspace.

        Returns:
            List of MCP instance dictionaries in YAML format
        """
        if not self.mcp_instance_service:
            return []

        try:
            instances = await self.mcp_instance_service.list()
            result = []

            for instance in instances:
                # Skip system instances
                if hasattr(instance, 'workspace_id') and instance.workspace_id == "system":
                    continue

                instance_dict: dict[str, Any] = {
                    "name": instance.name,
                    "server_spec_id": instance.server_spec_id,
                }

                if instance.description:
                    instance_dict["description"] = instance.description

                # Export environment variables from json_spec if present
                if instance.json_spec and "env_vars" in instance.json_spec:
                    instance_dict["env_vars"] = instance.json_spec["env_vars"]
                else:
                    instance_dict["env_vars"] = {}

                result.append(instance_dict)

            return result
        except Exception as e:
            # Log error but don't fail the entire export
            logger.warning(f"Failed to export MCP instances: {e}")
            return []

    async def _export_provider_configs(self) -> list[dict]:
        """Export provider configurations from the current workspace.

        Returns:
            List of provider config dictionaries in YAML format
        """
        if not self.provider_service:
            return []

        try:
            configs = await self.provider_service.list_provider_configs()
            result = []

            for config in configs:
                # Skip system configs
                if hasattr(config, 'workspace_id') and config.workspace_id == "system":
                    continue

                config_dict: dict[str, Any] = {
                    "name": config.name,
                    "provider_spec_id": str(config.provider_spec_id),
                    # API key is not exported - replaced with placeholder
                    "api_key_placeholder": "<REQUIRED>",
                }

                if config.description:
                    config_dict["description"] = config.description

                if config.endpoint_url:
                    config_dict["endpoint_url"] = config.endpoint_url

                result.append(config_dict)

            return result
        except Exception as e:
            # Log error but don't fail the entire export
            logger.warning(f"Failed to export provider configs: {e}")
            return []

    async def _export_skills(self) -> list[dict]:
        """Export skills from the current workspace.

        Returns:
            List of skill dictionaries in YAML format
        """
        if not self.skill_service:
            return []

        try:
            skills = await self.skill_service.list()
            result = []

            for skill in skills:
                # Skip system skills
                if hasattr(skill, "workspace_id") and skill.workspace_id == "system":
                    continue

                skill_dict: dict[str, Any] = {
                    "name": skill.name,
                }

                if skill.description:
                    skill_dict["description"] = skill.description

                # Export based on source type
                if skill.source_url:
                    # GitHub-sourced skill
                    skill_dict["github"] = skill.source_url
                elif skill.content:
                    # Content-only skill
                    skill_dict["content"] = skill.content
                # Note: PATH source type skills are exported as content
                # since the original path may not be available in target environment

                result.append(skill_dict)

            return result
        except Exception as e:
            logger.warning(f"Failed to export skills: {e}")
            return []

    async def import_workspace(
        self,
        yaml_content: str,
        options: ImportOptions | None = None,
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

            # Phase 2: Import resources
            # Build skill name -> ID mapping (including existing skills)
            skill_name_to_id: dict[str, UUID] = {}
            if self.skill_service:
                existing_skills = await self.skill_service.list()
                for skill in existing_skills:
                    skill_name_to_id[skill.name] = skill.id

            # Import skills FIRST (agents may reference them)
            for skill_yaml in config.skills:
                try:
                    skill = await self._import_skill(skill_yaml, options)
                    skill_name_to_id[skill.name] = skill.id
                    result.created_skills += 1
                except Exception as e:
                    if not options.skip_missing_dependencies:
                        raise
                    result.warnings.append(f"Failed to import skill '{skill_yaml.name}': {e}")

            # Import agents (can now reference skills)
            for agent_yaml in config.agents:
                try:
                    await self._import_agent(agent_yaml, options, skill_name_to_id)
                    result.created_agents += 1
                except Exception as e:
                    if not options.skip_missing_dependencies:
                        raise
                    result.warnings.append(f"Failed to import agent '{agent_yaml.name}': {e}")

            # Import MCP instances
            for mcp_yaml in config.mcp_instances:
                try:
                    await self._import_mcp_instance(mcp_yaml, options)
                    result.created_mcp_instances += 1
                except Exception as e:
                    if not options.skip_missing_dependencies:
                        raise
                    result.warnings.append(f"Failed to import MCP instance '{mcp_yaml.name}': {e}")

            # Import provider configs
            for provider_yaml in config.provider_configs:
                try:
                    await self._import_provider_config(provider_yaml, options)
                    result.created_provider_configs += 1
                except Exception as e:
                    if not options.skip_missing_dependencies:
                        raise
                    result.warnings.append(f"Failed to import provider config '{provider_yaml.name}': {e}")

            result.success = True
            return result

        except Exception as e:
            result.errors.append(f"Import failed: {e!s}")
            return result

    async def _validate_dependencies(self, config: WorkspaceConfigYAML) -> list[str]:
        """Validate that all referenced resources exist.

        Returns:
            List of validation error messages
        """
        errors = []

        # Validate code tools
        from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

        available_code_tools = get_code_tools_metadata()

        for agent in config.agents:
            if not agent.tools:
                continue

            for tool_config in agent.tools:
                if tool_config.type == "code" and tool_config.name not in available_code_tools:
                    errors.append(
                        f"Agent '{agent.name}': Unknown code tool "
                        f"'{tool_config.name}'. Available tools: "
                        f"{list(available_code_tools.keys())}"
                    )

        # Validate MCP server specs exist
        if config.mcp_instances and self.mcp_instance_service:
            try:
                # Get all available MCP server specs
                from agentarea_mcp.infrastructure.repository import MCPServerRepository

                mcp_repo = self.repository_factory.create_repository(MCPServerRepository)
                available_specs = await mcp_repo.list_all()
                available_spec_ids = {str(spec.id) for spec in available_specs}

                for mcp in config.mcp_instances:
                    if mcp.server_spec_id not in available_spec_ids:
                        errors.append(
                            f"MCP instance '{mcp.name}': Unknown server spec "
                            f"'{mcp.server_spec_id}'. Available specs: {list(available_spec_ids)}"
                        )
            except Exception as e:
                errors.append(f"Failed to validate MCP server specs: {e}")

        # Validate provider specs exist
        if config.provider_configs and self.provider_service:
            try:
                available_specs = await self.provider_service.list_provider_specs()
                available_spec_ids = {str(spec.id) for spec in available_specs}

                for provider in config.provider_configs:
                    if provider.provider_spec_id not in available_spec_ids:
                        errors.append(
                            f"Provider config '{provider.name}': Unknown provider spec "
                            f"'{provider.provider_spec_id}'. Available specs: {list(available_spec_ids)}"
                        )
            except Exception as e:
                errors.append(f"Failed to validate provider specs: {e}")

        # Validate skill references in agents
        # Build set of skill names that will be available after import
        available_skill_names: set[str] = set()

        # Add existing skills
        if self.skill_service:
            try:
                existing_skills = await self.skill_service.list()
                available_skill_names.update(s.name for s in existing_skills)
            except Exception as e:
                errors.append(f"Failed to get existing skills: {e}")

        # Add skills being imported (by name if provided, or will get name from content)
        for skill in config.skills:
            if skill.name:
                available_skill_names.add(skill.name)
            # Note: Skills without explicit names will be named from frontmatter during import

        # Validate agent skill references
        for agent in config.agents:
            if not agent.skill_names:
                continue
            for skill_name in agent.skill_names:
                if skill_name not in available_skill_names:
                    errors.append(
                        f"Agent '{agent.name}': References unknown skill '{skill_name}'. "
                        f"Make sure the skill is defined in the YAML or already exists."
                    )

        return errors

    async def _import_skill(
        self,
        skill_yaml: SkillYAML,
        options: ImportOptions,
        base_path: Path | None = None,
    ) -> "Skill":
        """Import a single skill from YAML.

        Args:
            skill_yaml: Skill configuration from YAML.
            options: Import options.
            base_path: Base directory for resolving relative paths.

        Returns:
            Created or updated Skill entity.
        """
        if not self.skill_service:
            raise RuntimeError("Skill service not available")

        # Check if skill with same name exists
        existing_skill = None
        if skill_yaml.name:
            existing_skill = await self.skill_service.get_by_name(skill_yaml.name)

        if existing_skill and not options.override_existing:
            raise ValueError(
                f"Skill '{skill_yaml.name}' already exists. Use override_existing=true to replace."
            )

        # Delete existing if overriding
        if existing_skill and options.override_existing:
            await self.skill_service.delete(existing_skill.id)

        # Create skill from appropriate source
        if skill_yaml.content:
            skill = await self.skill_service.create_from_content(
                content=skill_yaml.content,
                name=skill_yaml.name,
                description=skill_yaml.description,
            )
        elif skill_yaml.github:
            skill = await self.skill_service.create_from_github(
                github_url=skill_yaml.github,
                name=skill_yaml.name,
                description=skill_yaml.description,
            )
        elif skill_yaml.path:
            skill = await self.skill_service.create_from_path(
                path=skill_yaml.path,
                base_dir=base_path,
                name=skill_yaml.name,
                description=skill_yaml.description,
            )
        else:
            raise ValueError("Skill must have one of: content, github, or path")

        logger.info(f"Imported skill '{skill.name}' (id={skill.id})")
        return skill

    async def _import_agent(
        self,
        agent_yaml: AgentYAML,
        options: ImportOptions,
        skill_name_to_id: dict[str, UUID] | None = None,
    ) -> Agent:
        """Import a single agent from YAML.

        Args:
            agent_yaml: Agent configuration from YAML.
            options: Import options.
            skill_name_to_id: Mapping of skill names to IDs for resolving skill_names.

        Returns:
            Created or updated Agent entity.
        """
        # Check if agent with same name exists
        existing_agents = await self.agent_service.list()
        existing_agent = next(
            (a for a in existing_agents if a.name == agent_yaml.name),
            None,
        )

        if existing_agent and not options.override_existing:
            raise ValueError(
                f"Agent '{agent_yaml.name}' already exists. Use override_existing=true to replace."
            )

        # Convert tools to list of dicts
        tools_list = None
        if agent_yaml.tools:
            tools_list = [tool.model_dump(exclude_none=True) for tool in agent_yaml.tools]

        # Resolve skill_names to skill_ids
        skill_ids: list[UUID] | None = None
        if agent_yaml.skill_names and skill_name_to_id:
            skill_ids = []
            for skill_name in agent_yaml.skill_names:
                if skill_name in skill_name_to_id:
                    skill_ids.append(skill_name_to_id[skill_name])
                elif not options.skip_missing_dependencies:
                    raise ValueError(
                        f"Agent '{agent_yaml.name}' references unknown skill '{skill_name}'"
                    )
                else:
                    logger.warning(
                        f"Agent '{agent_yaml.name}': Skipping unknown skill '{skill_name}'"
                    )

        # Create or update agent
        if existing_agent and options.override_existing:
            # Update existing
            updated_agent = await self.agent_service.update_agent(
                id=UUID(str(existing_agent.id)),
                name=agent_yaml.name,
                description=agent_yaml.description,
                tools=tools_list,
                skill_ids=skill_ids,
            )
            if updated_agent is None:
                raise RuntimeError(f"Failed to update agent '{agent_yaml.name}'")
            return updated_agent
        else:
            # Create new (without model_id as per requirements)
            new_agent = await self.agent_service.create_agent(
                name=agent_yaml.name,
                description=agent_yaml.description,
                instruction=agent_yaml.instruction,
                model_id="",  # Empty string as per requirements (not None to avoid type error)
                tools=tools_list,
                events_config=None,  # No events for imported agents
                planning=agent_yaml.planning,
                skill_ids=skill_ids,
            )
            return new_agent

    async def _import_mcp_instance(
        self, mcp_yaml: MCPInstanceYAML, options: ImportOptions
    ) -> Any:
        """Import a single MCP server instance from YAML."""
        if not self.mcp_instance_service:
            raise RuntimeError("MCP instance service not available")

        # Check if instance with same name exists
        existing_instances = await self.mcp_instance_service.list()
        existing_instance = next(
            (i for i in existing_instances if i.name == mcp_yaml.name),
            None,
        )

        if existing_instance and not options.override_existing:
            raise ValueError(
                f"MCP instance '{mcp_yaml.name}' already exists. "
                "Use override_existing=true to replace."
            )

        # Build json_spec with environment variables
        json_spec: dict[str, Any] = {}
        if mcp_yaml.env_vars:
            json_spec["env_vars"] = mcp_yaml.env_vars

        # Create or update instance
        if existing_instance and options.override_existing:
            # Update existing
            from uuid import UUID

            updated_instance = await self.mcp_instance_service.update_instance(
                id=UUID(str(existing_instance.id)),
                name=mcp_yaml.name,
                description=mcp_yaml.description,
                json_spec=json_spec,
            )
            return updated_instance
        else:
            # Create new
            new_instance = await self.mcp_instance_service.create_instance(
                name=mcp_yaml.name,
                description=mcp_yaml.description,
                server_spec_id=mcp_yaml.server_spec_id,
                json_spec=json_spec,
            )
            return new_instance

    async def _import_provider_config(
        self, provider_yaml: ProviderConfigYAML, options: ImportOptions
    ) -> Any:
        """Import a single provider configuration from YAML."""
        if not self.provider_service:
            raise RuntimeError("Provider service not available")

        # Check if config with same name exists
        existing_configs = await self.provider_service.list_provider_configs()
        existing_config = next(
            (c for c in existing_configs if c.name == provider_yaml.name),
            None,
        )

        if existing_config and not options.override_existing:
            raise ValueError(
                f"Provider config '{provider_yaml.name}' already exists. "
                "Use override_existing=true to replace."
            )

        # Validate that API key is provided (not placeholder)
        api_key = provider_yaml.api_key_placeholder
        if api_key == "<REQUIRED>" or not api_key:
            raise ValueError(
                f"Provider config '{provider_yaml.name}': "
                "API key is required. Replace '<REQUIRED>' with actual API key."
            )

        from uuid import UUID

        provider_spec_id = UUID(provider_yaml.provider_spec_id)

        # Create or update config
        if existing_config and options.override_existing:
            # Update existing
            from uuid import UUID

            updated_config = await self.provider_service.update_provider_config(
                config_id=UUID(str(existing_config.id)),
                name=provider_yaml.name,
                api_key=api_key,
                endpoint_url=provider_yaml.endpoint_url,
            )
            return updated_config
        else:
            # Create new
            new_config = await self.provider_service.create_provider_config(
                provider_spec_id=provider_spec_id,
                name=provider_yaml.name,
                api_key=api_key,
                endpoint_url=provider_yaml.endpoint_url,
            )
            return new_config

