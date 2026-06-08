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

from agentarea_bundles.application.analyzer import mcp_is_unsupported, required_setup_errors
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


def _transport_fields(json_spec: dict[str, Any]) -> dict[str, Any]:
    """Extract the runtime transport portion of a package MCP json_spec."""
    spec_type = json_spec.get("type")
    out: dict[str, Any] = {"type": spec_type}
    if spec_type == "command":
        out["command"] = json_spec.get("command")
        if json_spec.get("args"):
            out["args"] = list(json_spec["args"])
    elif spec_type == "docker":
        out["image"] = json_spec.get("image")
    elif spec_type == "url":
        out["endpoint_url"] = json_spec.get("endpoint_url") or json_spec.get("url")
    return out


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
        user_context: Any,
    ) -> None:
        self._mcp_server_service = mcp_server_service
        self._mcp_instance_service = mcp_instance_service
        self._skill_service = skill_service
        self._skill_repository = skill_repository
        self._agent_service = agent_service
        self._agent_repository = agent_repository
        self._trigger_service = trigger_service
        self._trigger_repository = trigger_repository
        self._user_context = user_context

    async def install(self, package: Bundle, setup_values: dict[str, Any]) -> InstallResult:
        # Block on missing required setup before touching anything.
        block = required_setup_errors(package, setup_values)
        if block:
            raise BundleInstallError(
                "package is not installable: missing required setup", issues=block
            )

        result = InstallResult(bundle_name=package.name)

        mcp_tool_names = await self._install_mcps(package, setup_values, result)
        skill_ids = await self._install_skills(package, result)
        agent_ids = await self._install_agents(
            package, setup_values, mcp_tool_names, skill_ids, result
        )
        await self._install_automations(package, agent_ids, result)
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

            transport = _transport_fields(mcp.json_spec)
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
            instance_json: dict[str, Any] = {"type": transport["type"]}
            if resolved:
                instance_json[target] = resolved

            instance = await self._mcp_instance_service.create_instance(
                MCPServerInstanceCreate(
                    name=mcp.name,
                    server_spec_id=str(spec.id),
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
        return env_schema

    # -- skills -------------------------------------------------------------

    async def _install_skills(self, package: Bundle, result: InstallResult) -> dict[str, UUID]:
        """Returns {package skill key -> skill id}."""
        from agentarea_agents.schemas.skills_dto import SkillCreateFromContent

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

            if skill.source_type != "content":
                # github import is analyzed/declared but deferred for v0.1.0 install.
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.SKILL,
                        key=skill.key,
                        name=skill.name,
                        action=InstallAction.SKIPPED,
                        detail=f"source_type '{skill.source_type}' install not yet supported",
                    )
                )
                continue

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
        from agentarea_agents.schemas.import_export import McpToolConfig

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

            tools = [
                McpToolConfig(name=mcp_tool_names[ref])
                for ref in agent.mcps
                if ref in mcp_tool_names  # unsupported MCPs were skipped
            ]
            attached_skill_ids = [skill_ids[ref] for ref in agent.skills if ref in skill_ids]
            model_id = resolve_placeholders(agent.model or "", setup_values)

            created = await self._agent_service.create_agent(
                AgentCreate(
                    name=agent.name,
                    description="",
                    instruction=agent.instruction,
                    model_id=model_id,
                    tools=tools or None,
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
                description=auto.prompt,  # becomes the agent task query on each run
                agent_id=agent_id,
                trigger_type="cron",
                cron_expression=auto.cron,
                timezone=auto.timezone,
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
