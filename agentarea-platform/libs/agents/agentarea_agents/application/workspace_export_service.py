"""Export a workspace as a canonical, importable bundle."""

import logging
import re
from typing import TYPE_CHECKING, Any

import yaml
from agentarea_common.auth.authorization import assert_workspace_admin
from agentarea_common.base import RepositoryFactory, is_builtin
from agentarea_common.workspaces.lookup import load_workspace

from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.domain.models import Agent

if TYPE_CHECKING:
    from agentarea_agents.application.skill_service import SkillService

logger = logging.getLogger(__name__)


def _bundle_key(kind: str, name: str, identifier: Any) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    slug = slug[:64].rstrip("_") or "resource"
    suffix = re.sub(r"[^a-zA-Z0-9]", "", str(identifier or "")).lower()
    return f"{kind}_{slug}_{suffix}" if suffix else f"{kind}_{slug}"


def _setup_key(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return f"setup_{normalized or 'value'}"


class WorkspaceExportService:
    """Create a canonical bundle from workspace-owned resources."""

    def __init__(
        self,
        agent_service: AgentService,
        repository_factory: RepositoryFactory,
        mcp_instance_service: Any | None = None,
        skill_service: "SkillService | None" = None,
        trigger_repository: Any | None = None,
    ):
        self.agent_service = agent_service
        self.repository_factory = repository_factory
        self.mcp_instance_service = mcp_instance_service
        self.skill_service = skill_service
        self.trigger_repository = trigger_repository

    async def export_workspace(self) -> str:
        """Serialize exportable workspace resources using the bundle schema."""
        await assert_workspace_admin(self.repository_factory.user_context)
        workspace_id = self.repository_factory.user_context.workspace_id
        workspace = await load_workspace(workspace_id=workspace_id)
        if workspace is None:
            raise LookupError(f"Workspace {workspace_id} does not exist")

        # Bundles depend on agents for installation services, so import the
        # schema here rather than creating a module-level dependency cycle.
        from agentarea_bundles.schemas.bundle import (
            Bundle,
            BundleAgent,
            BundleAutomation,
            BundleChannel,
            BundleMcp,
            BundleSkill,
            SetupField,
            SetupFieldType,
        )

        skills = await self.skill_service.list() if self.skill_service else []
        bundle_skills, skill_keys = self._skills_to_bundle(skills, BundleSkill)

        agents = await self.agent_service.list()
        workspace_agents: list[Agent] = []
        for agent in agents:
            if is_builtin(agent):
                continue
            full = await self.agent_service.get_with_skills(agent.id)
            workspace_agents.append(full or agent)

        mcps, mcp_keys, setup_fields = await self._export_mcp_instances(
            BundleMcp, SetupField, SetupFieldType
        )
        bundle_agents, agent_keys = self._agents_to_bundle(
            workspace_agents,
            skill_keys,
            mcp_keys,
            setup_fields,
            BundleAgent,
            SetupField,
            SetupFieldType,
        )
        automations, channels, trigger_setup = await self._export_triggers(
            agent_keys,
            BundleAutomation,
            BundleChannel,
            SetupField,
            SetupFieldType,
        )
        setup_fields.extend(trigger_setup)

        bundle = Bundle(
            name=workspace.slug or _bundle_key("workspace", workspace.name, workspace_id),
            display_name=workspace.name,
            setup=setup_fields,
            mcps=mcps,
            skills=bundle_skills,
            agents=bundle_agents,
            channels=channels,
            automations=automations,
        )
        return yaml.safe_dump(
            bundle.model_dump(mode="json", exclude_none=True),
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    def _skills_to_bundle(
        self, skills: list[Any], bundle_skill_type: Any
    ) -> tuple[list[Any], dict[str, str]]:
        result = []
        skill_keys = {}
        for skill in skills:
            if is_builtin(skill):
                continue

            key = _bundle_key("skill", getattr(skill, "slug", None) or skill.name, skill.id)
            if not skill.content:
                raise ValueError(
                    f"Skill '{skill.name}' has no inline content for bundle installation"
                )
            bundle_skill = bundle_skill_type(
                key=key,
                name=skill.name,
                source_type="content",
                content=skill.content,
            )

            result.append(bundle_skill)
            skill_keys[str(skill.id)] = key
        return result, skill_keys

    async def _export_mcp_instances(
        self,
        bundle_mcp_type: Any,
        setup_field_type: Any,
        setup_field_enum: Any,
    ) -> tuple[list[Any], dict[str, str], list[Any]]:
        if not self.mcp_instance_service:
            return [], {}, []

        result = []
        mcp_keys = {}
        setup_fields = []
        for instance in await self.mcp_instance_service.list():
            if is_builtin(instance):
                continue

            key = _bundle_key("mcp", instance.name, instance.id)
            transport_spec = await self.mcp_instance_service.get_transport_spec_for_instance(
                instance
            )
            spec_type = transport_spec.get("type")
            if spec_type not in {"command", "docker", "url"}:
                raise ValueError(
                    f"MCP instance '{instance.name}' uses unsupported transport '{spec_type}'"
                )
            json_spec = {
                field: transport_spec[field]
                for field in ("type", "command", "args", "image", "endpoint_url")
                if field in transport_spec
            }

            bindings = {}
            for env_name in instance.get_configured_env_vars():
                setup_key = _setup_key(f"{key}_{env_name}")
                setup_fields.append(
                    setup_field_type(
                        key=setup_key,
                        label=f"{instance.name}: {env_name}",
                        type=setup_field_enum.SECRET,
                        required=True,
                        help=f"Provide {env_name} for {instance.name}.",
                    )
                )
                bindings[env_name] = f"${{setup.{setup_key}}}"

            result.append(
                bundle_mcp_type(
                    key=key,
                    name=instance.name,
                    json_spec=json_spec,
                    bindings=bindings,
                )
            )
            mcp_keys[instance.name] = key
        return result, mcp_keys, setup_fields

    def _agents_to_bundle(
        self,
        agents: list[Agent],
        skill_keys: dict[str, str],
        mcp_keys: dict[str, str],
        setup_fields: list[Any],
        bundle_agent_type: Any,
        setup_field_type: Any,
        setup_field_enum: Any,
    ) -> tuple[list[Any], dict[str, str]]:
        result = []
        agent_keys = {}

        for agent in agents:
            key = _bundle_key("agent", agent.name, agent.id)
            agent_keys[str(agent.id)] = key

        for agent in agents:
            key = agent_keys[str(agent.id)]
            # Model identifiers belong to their source workspace; ask the
            # importer to bind a model that exists in the destination.
            setup_key = _setup_key(f"model_{key}")
            setup_fields.append(
                setup_field_type(
                    key=setup_key,
                    label=f"Model for {agent.name}",
                    type=setup_field_enum.STRING,
                    required=True,
                    help="Choose a model available in the destination workspace.",
                )
            )
            model = f"${{setup.{setup_key}}}"
            agent_skills = []
            for skill in getattr(agent, "skills", None) or []:
                skill_key = skill_keys.get(str(skill.id))
                if skill_key:
                    agent_skills.append(skill_key)
                elif not is_builtin(skill):
                    raise ValueError(
                        f"Skill '{getattr(skill, 'name', skill.id)}' attached to "
                        f"agent '{agent.name}' could not be exported"
                    )

            toolsets = []
            agent_mcps = []
            raw_tools = getattr(agent, "tools", None) or []
            if isinstance(raw_tools, dict):
                raw_tools = raw_tools.get("tools", [])
            for tool in raw_tools:
                if hasattr(tool, "model_dump"):
                    tool = tool.model_dump()
                if not isinstance(tool, dict):
                    continue
                name = tool.get("name")
                if not isinstance(name, str):
                    continue
                tool_type = tool.get("type")
                if tool_type == "code" and name not in toolsets:
                    toolsets.append(name)
                elif tool_type == "mcp" and name in mcp_keys and mcp_keys[name] not in agent_mcps:
                    agent_mcps.append(mcp_keys[name])

            result.append(
                bundle_agent_type(
                    key=key,
                    name=agent.name,
                    instruction=agent.instruction or "",
                    model=model,
                    mcps=agent_mcps,
                    skills=agent_skills,
                    toolsets=toolsets,
                )
            )
        return result, agent_keys

    async def _export_triggers(
        self,
        agent_keys: dict[str, str],
        automation_type: Any,
        channel_type: Any,
        setup_field_type: Any,
        setup_field_enum: Any,
    ) -> tuple[list[Any], list[Any], list[Any]]:
        if not self.trigger_repository:
            return [], [], []

        automations = []
        channels = []
        setup_fields = []
        for trigger in await self.trigger_repository.list_all():
            trigger_kind = getattr(trigger.trigger_type, "value", trigger.trigger_type)
            agent_key = agent_keys.get(str(trigger.agent_id))
            if agent_key is None:
                logger.warning(
                    "Skipping trigger '%s' targeting an agent outside the bundle",
                    trigger.name,
                )
                continue
            if trigger.conditions:
                logger.warning(
                    "Skipping trigger '%s' with conditions not represented in bundles",
                    trigger.name,
                )
                continue

            task_parameters = trigger.task_parameters or {}
            if trigger_kind == "cron":
                if (
                    getattr(trigger, "data_extractor", None)
                    or getattr(trigger, "data_extractor_config", None)
                    or getattr(trigger, "data_extractor_state", None)
                ):
                    logger.warning(
                        "Skipping polling trigger '%s' not represented in bundles", trigger.name
                    )
                    continue
                prompt = task_parameters.get("text")
                if not isinstance(prompt, str) or not prompt.strip():
                    logger.warning("Skipping cron trigger '%s' without task text", trigger.name)
                    continue
                automations.append(
                    automation_type(
                        key=_bundle_key("automation", trigger.name, trigger.id),
                        cron=trigger.cron_expression,
                        timezone=trigger.timezone,
                        agent=agent_key,
                        prompt=prompt,
                        enabled=trigger.is_active,
                    )
                )
                continue

            if trigger_kind != "webhook":
                logger.warning(
                    "Skipping unsupported trigger '%s' of type '%s'",
                    trigger.name,
                    trigger_kind,
                )
                continue

            webhook_kind = getattr(trigger.webhook_type, "value", trigger.webhook_type)
            if webhook_kind not in {"generic", "telegram"}:
                logger.warning(
                    "Skipping unsupported webhook '%s' of type '%s'",
                    trigger.name,
                    webhook_kind,
                )
                continue
            allowed_methods = [
                method.upper() for method in getattr(trigger, "allowed_methods", ["POST"])
            ]
            if (
                getattr(trigger, "validation_rules", None)
                or getattr(trigger, "webhook_config", None)
                or getattr(trigger, "event_types", None)
                or allowed_methods != ["POST"]
            ):
                logger.warning(
                    "Skipping webhook trigger '%s' with configuration not represented in bundles",
                    trigger.name,
                )
                continue

            prompt = task_parameters.get("text")
            if not isinstance(prompt, str) or not prompt.strip():
                if webhook_kind == "telegram":
                    prompt = "Handle the incoming message: {{ message_text }}"
                else:
                    logger.warning("Skipping webhook trigger '%s' without task text", trigger.name)
                    continue

            bindings = {}
            if webhook_kind == "telegram":
                setup_key = _setup_key(f"telegram_bot_token_{trigger.id}")
                setup_fields.append(
                    setup_field_type(
                        key=setup_key,
                        label=f"Telegram bot token for {trigger.name}",
                        type=setup_field_enum.SECRET,
                        required=True,
                        help="Provide the bot token for the destination workspace.",
                    )
                )
                bindings["bot_token"] = f"${{setup.{setup_key}}}"

            channels.append(
                channel_type(
                    key=_bundle_key("channel", trigger.name, trigger.id),
                    type=webhook_kind,
                    name=trigger.name,
                    agent=agent_key,
                    bindings=bindings,
                    prompt=prompt,
                    enabled=trigger.is_active,
                )
            )

        return automations, channels, setup_fields
