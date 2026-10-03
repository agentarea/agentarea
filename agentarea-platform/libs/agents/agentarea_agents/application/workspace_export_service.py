"""Export a workspace as a canonical, importable bundle.

A bundle is meant to be shared, so no credential may travel in it. MCP secrets
(names listed in ``env_vars``) are never read; they become secret setup fields.
Values the source keeps in plain configuration are screened too, and anything
that carries a credential is replaced by a ``${setup.<key>}`` reference to a
secret setup field the importer fills in:

- an environment variable or header whose name looks like a credential, or
  whose value is a credentialed URL or an ``Authorization``-style value;
- an ``args`` entry that is a credentialed URL, the value of a credential flag
  (``--api-key=x``, ``--token x``, ``TOKEN=x``), or a credential header
  (``Authorization: Bearer x``);
- an ``endpoint_url`` that is a credentialed URL.

A URL is credentialed when it has a password in its userinfo, a query parameter
named like a credential, or an opaque path segment (24+ letters and digits, the
shape of per-user secret URLs). Setup keys are derived from the MCP key and the
position, so the same workspace always exports the same document.
"""

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlsplit

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


_CREDENTIAL_WORDS_RE = re.compile(
    r"token|secret|passw|pwd|api[_-]?key|apikey|access[_-]?key|private[_-]?key|"
    r"credential|bearer|cookie|session|authorization|auth[_-]?key|signature",
    re.IGNORECASE,
)
_CREDENTIAL_EXACT_NAMES = {"key", "sig", "auth", "pass", "code"}
_CREDENTIAL_VALUE_RE = re.compile(r"^(bearer|basic|token)\s+\S", re.IGNORECASE)
_OPAQUE_SEGMENT_RE = re.compile(r"^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9_\-]{24,}$")
_HEADER_ARG_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(\S.*)$")


def _is_credential_name(name: str) -> bool:
    normalized = name.strip().lstrip("-")
    return bool(_CREDENTIAL_WORDS_RE.search(normalized)) or (
        normalized.lower() in _CREDENTIAL_EXACT_NAMES
    )


def _is_url(value: str) -> bool:
    return "://" in value


def _url_carries_credentials(value: str) -> bool:
    try:
        parts = urlsplit(value)
    except ValueError:
        # Unparseable: nothing can vouch that it is credential-free.
        return True
    if parts.password is not None:
        return True
    if any(_is_credential_name(name) for name, _ in parse_qsl(parts.query)):
        return True
    return any(_OPAQUE_SEGMENT_RE.match(segment) for segment in parts.path.split("/"))


def _value_carries_credentials(value: str) -> bool:
    if _is_url(value):
        return _url_carries_credentials(value)
    return bool(_CREDENTIAL_VALUE_RE.match(value.strip()))


def _template_args(
    args: list[Any], mcp_key: str, secret_ref: Callable[[str, str], str]
) -> list[Any]:
    """Replace credential-carrying command arguments with secret setup references."""
    result: list[Any] = []
    value_is_credential = False
    for index, arg in enumerate(args):
        if not isinstance(arg, str):
            result.append(arg)
            value_is_credential = False
            continue
        field = f"{mcp_key}_arg_{index}"
        what = f"command argument {index + 1}"
        if value_is_credential and not arg.startswith("-"):
            # The value following a credential flag: --token <value>.
            result.append(secret_ref(field, what))
            value_is_credential = False
            continue
        value_is_credential = False

        flag, separator, value = arg.partition("=")
        header = _HEADER_ARG_RE.match(arg)
        if _is_url(arg) and not (separator and not _is_url(flag)):
            result.append(secret_ref(field, what) if _url_carries_credentials(arg) else arg)
        elif separator and value:
            # --api-key=<value>, TOKEN=<value>, --db=<credentialed url>
            if _is_credential_name(flag) or _value_carries_credentials(value):
                result.append(f"{flag}={secret_ref(field, what)}")
            else:
                result.append(arg)
        elif header and (
            _is_credential_name(header.group(1)) or _value_carries_credentials(header.group(2))
        ):
            result.append(f"{header.group(1)}: {secret_ref(field, what)}")
        else:
            value_is_credential = arg.startswith("-") and _is_credential_name(arg)
            result.append(arg)
    return result


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

        mcps, mcp_keys, builtin_mcp_refs, setup_fields = await self._export_mcp_instances(
            BundleMcp, SetupField, SetupFieldType
        )
        bundle_agents, agent_keys = self._agents_to_bundle(
            workspace_agents,
            skill_keys,
            mcp_keys,
            builtin_mcp_refs,
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
            if skill.source_type == "github" and skill.source_url:
                # The repository is the package: re-importing it brings back the
                # files SKILL.md references, which inline content would drop.
                bundle_skill = bundle_skill_type(
                    key=key,
                    name=skill.name,
                    source_type="github",
                    source_url=skill.source_url,
                )
            elif skill.content:
                bundle_skill = bundle_skill_type(
                    key=key,
                    name=skill.name,
                    source_type="content",
                    content=skill.content,
                )
            else:
                raise ValueError(
                    f"Skill '{skill.name}' has no inline content for bundle installation"
                )

            result.append(bundle_skill)
            skill_keys[str(skill.id)] = key
        return result, skill_keys

    async def _export_mcp_instances(
        self,
        bundle_mcp_type: Any,
        setup_field_type: Any,
        setup_field_enum: Any,
    ) -> tuple[list[Any], dict[str, str], set[str], list[Any]]:
        """Returns (mcps, {instance id and name -> key}, built-in refs, setup fields)."""
        if not self.mcp_instance_service:
            return [], {}, set(), []

        result = []
        mcp_keys: dict[str, str] = {}
        builtin_refs: set[str] = set()
        setup_fields: list[Any] = []
        for instance in await self.mcp_instance_service.list():
            if is_builtin(instance):
                builtin_refs.update({str(instance.id), instance.name})
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

            def secret_ref(field: str, what: str, *, name: str = instance.name) -> str:
                setup_key = _setup_key(field)
                setup_fields.append(
                    setup_field_type(
                        key=setup_key,
                        label=f"{name}: {what}",
                        type=setup_field_enum.SECRET,
                        required=True,
                        help=f"Provide {what} for {name}.",
                    )
                )
                return f"${{setup.{setup_key}}}"

            json_spec: dict[str, Any] = {"type": spec_type}
            for field in ("command", "image"):
                if field in transport_spec:
                    json_spec[field] = transport_spec[field]
            if isinstance(transport_spec.get("args"), list):
                json_spec["args"] = _template_args(transport_spec["args"], key, secret_ref)
            endpoint_url = transport_spec.get("endpoint_url")
            if isinstance(endpoint_url, str):
                json_spec["endpoint_url"] = (
                    secret_ref(f"{key}_endpoint_url", "endpoint URL")
                    if _url_carries_credentials(endpoint_url)
                    else endpoint_url
                )

            secret_names = instance.get_configured_env_vars()
            bindings = {
                env_name: secret_ref(f"{key}_{env_name}", env_name) for env_name in secret_names
            }
            for field in ("environment", "headers"):
                values = transport_spec.get(field)
                if not isinstance(values, dict):
                    continue
                plain: dict[str, Any] = {}
                for name, value in values.items():
                    if name in bindings:
                        continue
                    if _is_credential_name(name) or (
                        isinstance(value, str) and _value_carries_credentials(value)
                    ):
                        bindings[name] = secret_ref(f"{key}_{name}", name)
                    else:
                        plain[name] = value
                if plain:
                    json_spec[field] = plain

            result.append(
                bundle_mcp_type(
                    key=key,
                    name=instance.name,
                    json_spec=json_spec,
                    bindings=bindings,
                )
            )
            # Agents reference an MCP by instance name or, when attached in
            # the UI, by instance id.
            mcp_keys[str(instance.id)] = key
            mcp_keys[instance.name] = key
        return result, mcp_keys, builtin_refs, setup_fields

    def _agents_to_bundle(
        self,
        agents: list[Agent],
        skill_keys: dict[str, str],
        mcp_keys: dict[str, str],
        builtin_mcp_refs: set[str],
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
                if name is None:
                    continue
                name = str(name)
                tool_type = tool.get("type")
                if tool_type == "code" and name not in toolsets:
                    toolsets.append(name)
                elif tool_type == "mcp":
                    mcp_key = mcp_keys.get(name)
                    if mcp_key is None:
                        if name in builtin_mcp_refs:
                            continue
                        raise ValueError(
                            f"MCP '{name}' attached to agent '{agent.name}' could not be "
                            "exported: it is not an MCP connection of this workspace"
                        )
                    if mcp_key not in agent_mcps:
                        agent_mcps.append(mcp_key)

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
