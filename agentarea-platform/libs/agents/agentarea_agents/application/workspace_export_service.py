"""Service for exporting a workspace's configuration as YAML.

There is no import counterpart: recreating a workspace goes through the
platform toolsets (``agentarea/agents``, ``agentarea/mcp_servers``, ...) or
bundle install, both of which take secrets as explicit inputs rather than
round-tripping placeholders through a file.
"""

import logging
from typing import TYPE_CHECKING, Any

import yaml
from agentarea_common.base import RepositoryFactory, is_builtin

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent

if TYPE_CHECKING:
    from agentarea_agents.application.skill_service import SkillService
    from agentarea_agents.domain.skill_models import Skill

logger = logging.getLogger(__name__)


class WorkspaceExportService:
    """Serialize the caller's workspace to the WorkspaceConfigYAML shape."""

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
        # Read the workspace's skills once and serve both the skills section and
        # the agent name lookup from it. Only workspace-owned skills are
        # exportable, so the catalog is not requested at all.
        skills: list[Skill] = []
        if self.skill_service:
            try:
                skills = await self.skill_service.list()
            except Exception as e:
                logger.warning(f"Failed to list skills: {e}")

        skills_yaml = self._skills_to_yaml(skills)
        skill_id_to_name = {str(s.id): s.name for s in skills}

        # Get all workspace-scoped resources (exclude system resources).
        # Refetch each agent with its skills eager-loaded to avoid a
        # MissingGreenlet error when the lazy relationship is accessed outside
        # the original async session scope.
        agents = await self.agent_service.list()
        workspace_agents_raw = [a for a in agents if not is_builtin(a)]
        workspace_agents: list[Agent] = []
        for a in workspace_agents_raw:
            full = await self.agent_service.get_with_skills(a.id)
            workspace_agents.append(full or a)

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

            # Add a2ui_enabled if present
            if agent.a2ui_enabled is not None:
                agent_dict["a2ui_enabled"] = agent.a2ui_enabled

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
                # Skip platform-official instances
                if is_builtin(instance):
                    continue

                instance_dict: dict[str, Any] = {
                    "name": instance.name,
                    "server_spec_id": instance.server_spec_id,
                }

                if instance.description:
                    instance_dict["description"] = instance.description

                # json_spec["env_vars"] is the list of *names* of the instance's
                # secret env vars -- the values live in the secret manager and
                # cannot be exported. The YAML contract is a name -> placeholder
                # mapping, so dumping the raw list here produced a file that
                # failed its own import schema.
                instance_dict["env_vars"] = dict.fromkeys(
                    instance.get_configured_env_vars(), "<REQUIRED>"
                )

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
                # Skip platform-official configs
                if is_builtin(config):
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

    def _skills_to_yaml(self, skills: list["Skill"]) -> list[dict]:
        """Convert already-loaded workspace skills to YAML dictionaries."""
        result = []

        for skill in skills:
            # Skip platform-official skills
            if is_builtin(skill):
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
