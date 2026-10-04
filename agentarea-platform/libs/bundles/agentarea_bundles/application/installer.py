"""Install orchestrator.

Decomposes an :class:`Bundle` into calls against the existing domain
services, in dependency order:

    setup values -> MCP instances -> skills -> agents -> cron automations

The installer never re-implements domain logic (secret storage, scheduling,
tool wiring) — it composes the services that already own it. It is idempotent
by entity name: re-running after a partial failure reuses what already exists
rather than creating duplicates.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from agentarea_common.auth.authorization import assert_workspace_admin

from agentarea_bundles.application.analyzer import (
    mcp_is_unsupported,
    policy_as_rule,
    required_setup_errors,
)
from agentarea_bundles.schemas.bundle import (
    Bundle,
    BundleMcp,
    SetupFieldType,
    resolve_placeholders,
    setup_refs,
)
from agentarea_bundles.schemas.preview import EntityKind
from agentarea_bundles.schemas.result import (
    InstallAction,
    InstalledEntity,
    InstallResult,
)

logger = logging.getLogger(__name__)


class BundleInstallError(Exception):
    """Raised when a package cannot be installed (e.g. missing required setup)."""

    def __init__(self, message: str, issues: list[Any] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


def _transport_fields(json_spec: dict[str, Any], setup_values: dict[str, Any]) -> dict[str, Any]:
    """Extract the runtime transport portion of a package MCP json_spec.

    ``args`` and ``endpoint_url`` may carry ``${setup.x}`` references (an
    exported workspace templates credentials out of them); they are resolved
    here, since the runtime reads both verbatim.
    """

    def resolve(value: Any) -> Any:
        return resolve_placeholders(value, setup_values) if isinstance(value, str) else value

    spec_type = json_spec.get("type")
    out: dict[str, Any] = {"type": spec_type}
    if spec_type == "command":
        out["command"] = json_spec.get("command")
        if json_spec.get("args"):
            out["args"] = [resolve(arg) for arg in json_spec["args"]]
    elif spec_type == "docker":
        out["image"] = json_spec.get("image")
    elif spec_type == "url":
        out["endpoint_url"] = resolve(json_spec.get("endpoint_url") or json_spec.get("url"))
    return out


def _plain_config(json_spec: dict[str, Any], field: str) -> dict[str, Any]:
    """Non-secret environment variables or headers written literally in the spec."""
    values = json_spec.get(field)
    return dict(values) if isinstance(values, dict) else {}


class BundleInstaller:
    """Orchestrates creation of package entities via existing services."""

    def __init__(
        self,
        *,
        mcp_server_service: Any,
        mcp_instance_service: Any,
        skill_service: Any,
        skill_repository: Any,
        agent_service: Any,
        agent_repository: Any,
        trigger_service: Any,
        trigger_repository: Any,
        governance_service: Any,
        user_context: Any,
        secret_manager: Any = None,
    ) -> None:
        self._mcp_server_service = mcp_server_service
        self._mcp_instance_service = mcp_instance_service
        self._skill_service = skill_service
        self._skill_repository = skill_repository
        self._agent_service = agent_service
        self._agent_repository = agent_repository
        self._trigger_service = trigger_service
        self._trigger_repository = trigger_repository
        self._governance_service = governance_service
        self._user_context = user_context
        self._secret_manager = secret_manager

    async def install(self, package: Bundle, setup_values: dict[str, Any]) -> InstallResult:
        # Block on missing required setup before touching anything.
        block = required_setup_errors(package, setup_values)
        if block:
            raise BundleInstallError(
                "package is not installable: missing required setup", issues=block
            )
        # Policies install last, but each step before them commits on its own, so
        # a refusal there would leave a partial install behind. Ask up front.
        if package.policies:
            await assert_workspace_admin(self._user_context)

        result = InstallResult(bundle_name=package.name)

        mcp_tool_names = await self._install_mcps(package, setup_values, result)
        skill_ids = await self._install_skills(package, result)
        agent_ids = await self._install_agents(
            package, setup_values, mcp_tool_names, skill_ids, result
        )
        await self._install_channels(package, setup_values, agent_ids, result)
        await self._install_automations(package, agent_ids, result)
        await self._install_policies(package, agent_ids, result)
        return result

    # -- MCP ----------------------------------------------------------------

    async def _install_mcps(
        self, package: Bundle, setup_values: dict[str, Any], result: InstallResult
    ) -> dict[str, str]:
        """Returns {package mcp key -> instance name to use in agent tools}."""
        from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerInstanceCreate

        tool_names: dict[str, str] = {}
        for mcp in package.mcps:
            reason = mcp_is_unsupported(mcp)
            if reason:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=mcp.name,
                        action=InstallAction.SKIPPED,
                        detail=reason,
                    )
                )
                continue

            existing = await self._mcp_instance_service.get_by_name(mcp.name)
            if existing:
                tool_names[mcp.key] = mcp.name
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=mcp.name,
                        action=InstallAction.REUSED,
                        id=str(existing.id),
                    )
                )
                continue

            transport = _transport_fields(mcp.json_spec, setup_values)
            spec_kwargs: dict[str, Any] = {
                "name": mcp.name,
                "description": f"Imported from package '{package.name}'",
                "env_schema": self._build_env_schema(mcp, package),
                "json_spec": transport,
            }
            if transport["type"] == "command":
                command = transport.get("command")
                spec_kwargs["cmd"] = [command, *transport.get("args", [])] if command else None
            elif transport["type"] == "docker":
                spec_kwargs["docker_image_url"] = transport.get("image")
            elif transport["type"] == "url":
                spec_kwargs["remote_url"] = transport.get("endpoint_url")

            spec = await self._mcp_server_service.create_mcp_server(MCPServerCreate(**spec_kwargs))

            target = "headers" if transport["type"] == "url" else "environment"
            resolved = {
                env_name: resolve_placeholders(ref, setup_values)
                for env_name, ref in mcp.bindings.items()
            }
            instance_json: dict[str, Any] = {}
            for field in ("environment", "headers"):
                values = _plain_config(mcp.json_spec, field)
                if field == target:
                    values.update(resolved)
                if values:
                    instance_json[field] = values

            instance = await self._mcp_instance_service.create_instance(
                MCPServerInstanceCreate(
                    name=mcp.name,
                    server_spec_id=spec.id,
                    json_spec=instance_json,
                )
            )
            if instance is None:
                raise BundleInstallError(f"failed to create MCP instance '{mcp.name}'")

            tool_names[mcp.key] = mcp.name
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.MCP,
                    key=mcp.key,
                    name=mcp.name,
                    action=InstallAction.CREATED,
                    id=str(instance.id),
                )
            )
        return tool_names

    def _build_env_schema(self, mcp: BundleMcp, package: Bundle) -> list[dict[str, Any]]:
        """Build the spec env_schema, flagging secrets by the setup field type.

        We do not rely on the MCP service's name-based secret heuristic — the
        package already declares which inputs are secrets via SetupField.type.
        Literal environment/header values are plain configuration by definition.
        """
        env_schema: list[dict[str, Any]] = []
        for env_name, ref in mcp.bindings.items():
            refs = setup_refs(ref)
            field = package.setup_field(refs[0]) if refs else None
            is_secret = bool(field and field.type is SetupFieldType.SECRET)
            env_schema.append(
                {
                    "name": env_name,
                    "description": f"{env_name} for {mcp.name}",
                    "isSecret": is_secret,
                }
            )
        for config_field in ("environment", "headers"):
            for name in _plain_config(mcp.json_spec, config_field):
                if name in mcp.bindings:
                    continue
                env_schema.append(
                    {
                        "name": str(name),
                        "description": f"{name} for {mcp.name}",
                        "isSecret": False,
                    }
                )
        return env_schema

    # -- skills -------------------------------------------------------------

    async def _install_skills(self, package: Bundle, result: InstallResult) -> dict[str, UUID]:
        """Returns {package skill key -> skill id}."""
        from agentarea_agents.infrastructure.github_skill_importer import (
            GitHubSkillImporterError,
        )
        from agentarea_agents.schemas.skills_dto import (
            SkillCreateFromContent,
            SkillImportFromGithub,
        )

        skill_ids: dict[str, UUID] = {}
        for skill in package.skills:
            existing = await self._skill_repository.get_by_name(skill.name)
            if existing:
                skill_ids[skill.key] = existing.id
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.SKILL,
                        key=skill.key,
                        name=skill.name,
                        action=InstallAction.REUSED,
                        id=str(existing.id),
                    )
                )
                continue

            if skill.source_type == "github":
                try:
                    created = await self._skill_service.create_from_github(
                        SkillImportFromGithub(github_url=skill.source_url or "", name=skill.name)
                    )
                except (GitHubSkillImporterError, ValueError) as exc:
                    logger.warning(
                        "Failed to import skill '%s' from %s",
                        skill.name,
                        skill.source_url,
                        exc_info=True,
                    )
                    raise BundleInstallError(
                        f"failed to import skill '{skill.name}' from {skill.source_url}: {exc}"
                    ) from exc
            else:
                created = await self._skill_service.create_from_content(
                    SkillCreateFromContent(
                        content=skill.content or "",
                        name=skill.name,
                        description=None,
                    )
                )
            skill_ids[skill.key] = created.id
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.SKILL,
                    key=skill.key,
                    name=skill.name,
                    action=InstallAction.CREATED,
                    id=str(created.id),
                )
            )
        return skill_ids

    # -- agents -------------------------------------------------------------

    async def _install_agents(
        self,
        package: Bundle,
        setup_values: dict[str, Any],
        mcp_tool_names: dict[str, str],
        skill_ids: dict[str, UUID],
        result: InstallResult,
    ) -> dict[str, UUID]:
        """Returns {package agent key -> agent id}."""
        from agentarea_agents.schemas.dto import AgentCreate
        from agentarea_agents.schemas.import_export import CodeToolConfig, McpToolConfig, ToolConfig

        agent_ids: dict[str, UUID] = {}
        for agent in package.agents:
            existing = await self._agent_repository.get_agent_by_name(agent.name)
            if existing:
                agent_ids[agent.key] = existing.id
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AGENT,
                        key=agent.key,
                        name=agent.name,
                        action=InstallAction.REUSED,
                        id=str(existing.id),
                    )
                )
                continue

            tools: list[ToolConfig] = [
                *(CodeToolConfig(name=name) for name in agent.toolsets),
                *(
                    McpToolConfig(name=mcp_tool_names[ref])
                    for ref in agent.mcps
                    if ref in mcp_tool_names  # unsupported MCPs were skipped
                ),
            ]
            attached_skill_ids = [skill_ids[ref] for ref in agent.skills if ref in skill_ids]
            model_id = resolve_placeholders(agent.model or "", setup_values)

            created = await self._agent_service.create_agent(
                AgentCreate(
                    name=agent.name,
                    description="",
                    instruction=agent.instruction,
                    model_id=model_id,
                    tools=tools,
                    skill_ids=attached_skill_ids or None,
                )
            )
            agent_ids[agent.key] = created.id
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.AGENT,
                    key=agent.key,
                    name=agent.name,
                    action=InstallAction.CREATED,
                    id=str(created.id),
                )
            )
        return agent_ids

    # -- channels -----------------------------------------------------------

    async def _install_channels(
        self,
        package: Bundle,
        setup_values: dict[str, Any],
        agent_ids: dict[str, UUID],
        result: InstallResult,
    ) -> None:
        """Provision messaging channels (e.g. Telegram) as inbound triggers.

        A channel becomes a webhook trigger bound to its agent: a message to the
        bot creates a task, and the reply is delivered back on the same chat. The
        bot token is resolved from setup and stored encrypted under the exact key
        the outbound delivery adapter reads — ``channel_cred:{type}:{trigger_id}``
        (see channels/adapters.py ``_resolve_token``). Imported disabled by
        default; the user activates after pointing the bot at the webhook URL.
        """
        import json

        from agentarea_triggers.schemas.dto import TriggerCreate

        existing_names = {t.name for t in await self._trigger_repository.list_all()}
        for channel in package.channels:
            trigger_name = f"{package.name}:{channel.key}"
            agent_id = agent_ids.get(channel.agent)
            if agent_id is None:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.CHANNEL,
                        key=channel.key,
                        name=trigger_name,
                        action=InstallAction.SKIPPED,
                        detail=f"agent '{channel.agent}' was not created",
                    )
                )
                continue
            if trigger_name in existing_names:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.CHANNEL,
                        key=channel.key,
                        name=trigger_name,
                        action=InstallAction.REUSED,
                    )
                )
                continue

            credentials = {
                name: resolve_placeholders(ref, setup_values)
                for name, ref in channel.bindings.items()
            }

            dto = TriggerCreate(
                name=trigger_name,
                description=channel.name,
                agent_id=agent_id,
                trigger_type="webhook",
                webhook_type=channel.type,
                # Under "text", not "prompt": this is the standing instruction
                # used when an inbound message carries none of its own, and
                # "text" is the key the execution path reads.
                task_parameters={"text": channel.prompt},
                enabled=channel.enabled,
            )
            domain = dto.to_domain(
                created_by=self._user_context.user_id,
                workspace_id=self._user_context.workspace_id,
            )
            trigger = await self._trigger_service.create_trigger(domain)

            # Store credentials where the outbound delivery adapter looks them up.
            if credentials and self._secret_manager is not None:
                secret_name = f"channel_cred:{channel.type}:{trigger.id}"
                await self._secret_manager.set_secret(secret_name, json.dumps(credentials))

            if not channel.enabled:
                await self._trigger_service.disable_trigger(trigger.id)

            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.CHANNEL,
                    key=channel.key,
                    name=trigger_name,
                    action=InstallAction.CREATED,
                    id=str(trigger.id),
                    detail=f"{channel.type} · enabled={channel.enabled}",
                )
            )

    # -- automations --------------------------------------------------------

    async def _install_automations(
        self, package: Bundle, agent_ids: dict[str, UUID], result: InstallResult
    ) -> None:
        from agentarea_triggers.schemas.dto import TriggerCreate

        existing_names = {t.name for t in await self._trigger_repository.list_all()}
        for auto in package.automations:
            trigger_name = f"{package.name}:{auto.key}"
            agent_id = agent_ids.get(auto.agent)
            if agent_id is None:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AUTOMATION,
                        key=auto.key,
                        name=trigger_name,
                        action=InstallAction.SKIPPED,
                        detail=f"agent '{auto.agent}' was not created",
                    )
                )
                continue
            if trigger_name in existing_names:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AUTOMATION,
                        key=auto.key,
                        name=trigger_name,
                        action=InstallAction.REUSED,
                    )
                )
                continue

            dto = TriggerCreate(
                name=trigger_name,
                description=f"Runs {auto.cron} ({auto.timezone})",
                agent_id=agent_id,
                trigger_type="cron",
                cron_expression=auto.cron,
                timezone=auto.timezone,
                # The prompt is the task query, so it goes where the execution
                # path reads it. It used to be written into description, which
                # worked only because description stood in for a missing task
                # text -- and that stand-in is gone.
                task_parameters={"text": auto.prompt},
                enabled=auto.enabled,
            )
            domain = dto.to_domain(
                created_by=self._user_context.user_id,
                workspace_id=self._user_context.workspace_id,
            )
            trigger = await self._trigger_service.create_trigger(domain)
            # TriggerCreate.to_domain does not carry the enabled flag and
            # create_trigger schedules cron unconditionally. Explicitly disable
            # so imported automations honour enabled=false: this deactivates the
            # trigger and pauses its schedule, so the agent never runs before the
            # user activates it.
            if not auto.enabled:
                await self._trigger_service.disable_trigger(trigger.id)
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.AUTOMATION,
                    key=auto.key,
                    name=trigger_name,
                    action=InstallAction.CREATED,
                    id=str(trigger.id),
                    detail=f"enabled={auto.enabled}",
                )
            )

    # -- policies -----------------------------------------------------------

    async def _install_policies(
        self, package: Bundle, agent_ids: dict[str, UUID], result: InstallResult
    ) -> None:
        from agentarea_governance.domain.rules import (
            PolicyEffect,
            PolicySubjectType,
            assert_enforceable,
        )

        for policy in package.policies:
            # Resolve the portable subject reference to a concrete (type, id).
            if policy.subject == "workspace":
                subject_type = PolicySubjectType.WORKSPACE
                subject_id = self._user_context.workspace_id
            else:
                agent_id = agent_ids.get(policy.subject)
                if agent_id is None:
                    result.entities.append(
                        InstalledEntity(
                            kind=EntityKind.POLICY,
                            key=policy.key,
                            name=policy.key,
                            action=InstallAction.SKIPPED,
                            detail=f"agent '{policy.subject}' was not created",
                        )
                    )
                    continue
                subject_type = PolicySubjectType.AGENT
                subject_id = str(agent_id)

            effect = PolicyEffect(policy.effect)
            rule = policy_as_rule(policy, subject_id)

            # `install` is reachable without an analyze pass (the route accepts a
            # bundle payload directly), so this is the only guard on that path.
            # A rule the compiler cannot read installs as a row that silently
            # never enforces — the UI would then advertise a cap or an approval
            # gate that does not exist. Skip it with the reason instead.
            try:
                assert_enforceable(rule)
            except ValueError as exc:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.POLICY,
                        key=policy.key,
                        name=policy.key,
                        action=InstallAction.SKIPPED,
                        detail=f"would never enforce: {exc}",
                    )
                )
                continue

            # Idempotent by (subject, target, effect): rules have no name.
            existing = await self._governance_service.list_rules(
                subject_type=subject_type,
                subject_id=subject_id,
                target=policy.target,
                effect=effect,
            )
            if existing:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.POLICY,
                        key=policy.key,
                        name=policy.key,
                        action=InstallAction.REUSED,
                        id=str(existing[0].id) if existing[0].id else None,
                    )
                )
                continue

            created = await self._governance_service.create_rule(rule=rule)
            detail = f"{policy.effect} {policy.target} on {policy.subject}"
            if policy.message:
                detail = f"{detail} — {policy.message}"
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.POLICY,
                    key=policy.key,
                    name=policy.key,
                    action=InstallAction.CREATED,
                    id=str(created.id) if created.id else None,
                    detail=detail,
                )
            )
