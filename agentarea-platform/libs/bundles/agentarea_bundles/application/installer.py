"""Install orchestrator.

Decomposes an :class:`Bundle` into calls against the existing domain
services, in dependency order:

    setup values -> MCP instances -> skills -> agents -> channels -> automations -> policies

The installer never re-implements domain logic (secret storage, scheduling,
tool wiring) — it composes the services that already own it. An entity an
earlier install of the same bundle created is resolved by its recorded id and
updated in place when its spec changed; anything else is matched by name and
reused unchanged.

Each service commits on its own, so an install that only creates is made
all-or-nothing by compensation: every entity it creates is recorded with how to
delete it, and a failure deletes them again, newest first, before the error
propagates. Once a redeploy has updated something in place, that update may
already point at what this deploy created, so a later failure keeps both and
the caller records what was written; the next deploy finishes the rest.
"""

from __future__ import annotations

import io
import json
import logging
import secrets
import zipfile
from collections.abc import Awaitable, Callable, Collection
from typing import Any
from uuid import UUID

from agentarea_common.auth.authorization import assert_workspace_admin

from agentarea_bundles.application.analyzer import (
    EDIT_GUARDED,
    GITHUB_SKILL_NOT_APPLIED,
    MCP_NOT_APPLIED,
    ORPHANED_DETAIL,
    BundleAnalyzer,
    PriorInstall,
    bundle_entities,
    channel_credentials,
    context_secret_errors,
    effective_setup,
    linked_id,
    mcp_is_unsupported,
    policy_as_rule,
    remembered_setup,
    required_setup_errors,
    spec_fingerprint,
    supplied_keys,
    trigger_name,
)
from agentarea_bundles.schemas.bundle import (
    Bundle,
    BundleAutomation,
    BundleChannel,
    BundleMcp,
    BundleSkill,
    SetupFieldType,
    resolve_placeholders,
    setup_refs,
)
from agentarea_bundles.schemas.preview import EntityKind, IssueSeverity, PreviewIssue
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


class BundleValidationError(BundleInstallError):
    """The bundle or its setup values are invalid; nothing was left installed."""


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


def _plain_config(json_spec: dict[str, Any] | None, field: str) -> dict[str, Any]:
    """Non-secret environment variables or headers written literally in the spec."""
    values = (json_spec or {}).get(field)
    return dict(values) if isinstance(values, dict) else {}


def _skill_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return buffer.getvalue()


def automation_trigger(
    package: Bundle, auto: BundleAutomation, agent_id: UUID, user_context: Any
) -> Any:
    """The domain cron trigger an automation creates; also what a plan validates."""
    from agentarea_triggers.schemas.dto import TriggerCreate

    return TriggerCreate(
        name=trigger_name(package, auto.key),
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
    ).to_domain(created_by=user_context.user_id, workspace_id=user_context.workspace_id)


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
        may_edit: Callable[[EntityKind, str], Awaitable[bool]] | None = None,
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
        self._may_edit = may_edit
        self._approved: frozenset[tuple[EntityKind, str]] = frozenset()
        self._prior: PriorInstall | None = None
        self._package: Bundle
        self._values: dict[str, Any] = {}
        self._supplied: set[str] = set()
        self.result = InstallResult(bundle_name="")
        # (what, delete, entities recorded before it) for each thing this install
        # created, oldest first.
        self._created: list[tuple[str, Callable[[], Awaitable[Any]], int]] = []
        # Set once an update is applied in place; from then on a failure keeps what was created.
        self.updated_in_place = False

    async def get_entity(self, kind: EntityKind, entity_id: str) -> Any | None:
        """Resolve a recorded entity id through the service that owns that kind."""
        ref = UUID(entity_id)
        if kind is EntityKind.MCP:
            return await self._mcp_instance_service.get(ref)
        if kind is EntityKind.SKILL:
            return await self._skill_service.get(ref)
        if kind is EntityKind.AGENT:
            return await self._agent_service.get(ref)
        if kind in (EntityKind.CHANNEL, EntityKind.AUTOMATION):
            return await self._trigger_service.get_trigger(ref)
        return await self._governance_service.get_rule(rule_id=ref)

    async def _owned(self, kind: EntityKind, key: str) -> tuple[UUID, Any] | None:
        """The live entity an earlier install of this bundle created for ``key``."""
        ref = self._prior.owned(kind, key) if self._prior else None
        if ref is None or ref.id is None:
            return None
        entity = await self.get_entity(kind, ref.id)
        if entity is None:
            return None
        return UUID(ref.id), entity

    def _fingerprint(self, spec: Any) -> str:
        return spec_fingerprint(self._package, spec, self._values)

    def _applied(self, kind: EntityKind, key: str) -> str | None:
        return self._prior.fingerprint(kind, key) if self._prior else None

    def _needs_update(
        self, kind: EntityKind, spec: Any, depends_on: list[tuple[EntityKind, str]]
    ) -> bool:
        """The resolved spec changed since the last install, or a dependency's id did."""
        if self._prior is None or self._prior.changed(kind, spec.key, self._fingerprint(spec)):
            return True
        return self._prior.deps_changed(
            depends_on, lambda kind, key: linked_id(self.result, kind, key)
        )

    async def _authorize_update(self, kind: EntityKind, key: str, entity_id: UUID) -> None:
        """Write only what the authorized plan approved, after the edit check its route makes."""
        refusal = None
        if (kind, key) not in self._approved:
            refusal = f"{kind} '{key}' would be updated, but the deploy plan did not approve it"
        elif (
            kind in EDIT_GUARDED
            and self._may_edit is not None
            and not await self._may_edit(kind, str(entity_id))
        ):
            refusal = f"{kind} '{key}' would be updated, but you may not edit {kind} {entity_id}"
        if refusal:
            raise BundleInstallError(
                refusal,
                issues=[
                    PreviewIssue(severity=IssueSeverity.BLOCK, message=refusal, entity_key=key)
                ],
            )

    def _skipped(self, kind: EntityKind, key: str, name: str, detail: str) -> InstalledEntity:
        """A skipped key stays owned when an earlier install created it, so it is managed again once fixed."""
        ref = self._prior.owned(kind, key) if self._prior else None
        return InstalledEntity(
            kind=kind,
            key=key,
            name=name,
            action=InstallAction.SKIPPED,
            id=ref.id if ref else None,
            detail=detail,
            fingerprint=self._applied(kind, key) if ref else None,
        )

    def _track(self, what: str, delete: Callable[[], Awaitable[Any]]) -> None:
        self._created.append((what, delete, len(self.result.entities)))

    async def _undo_created(self, *, unfinished_only: bool = False) -> None:
        """Delete what this install created, newest first; keep going past failures.

        ``unfinished_only`` removes just the parts of an entity whose creation
        the failure interrupted: nothing was recorded after them.
        """
        recorded = len(self.result.entities)
        while self._created:
            what, delete, before = self._created.pop()
            if unfinished_only and before < recorded:
                break
            try:
                await delete()
            except Exception:
                logger.exception("Failed to remove %s after a failed bundle install", what)

    async def install(
        self,
        package: Bundle,
        setup_values: dict[str, Any],
        prior: PriorInstall | None = None,
        approved_updates: Collection[tuple[EntityKind, str]] = frozenset(),
        writes_policies: bool | None = None,
    ) -> InstallResult:
        """Install ``package``; an entity a prior install created is updated only if approved.

        ``writes_policies`` says whether the plan creates or updates a policy;
        without a plan, any policy in the package counts.
        """
        self._prior = prior
        self._approved = frozenset(approved_updates)
        self._package = package
        self._values = effective_setup(package, setup_values, prior)
        self._supplied = supplied_keys(setup_values)
        # Refuse whatever analyze refuses, plus missing required setup, before
        # touching anything, so the common refusals need no compensation.
        await self._refuse_blocking_issues(package, setup_values)
        # Policies install last; ask for admin up front rather than undo the rest.
        if package.policies if writes_policies is None else writes_policies:
            await assert_workspace_admin(self._user_context)

        result = self.result = InstallResult(
            bundle_name=package.name, setup_values=remembered_setup(package, setup_values, prior)
        )
        self._created = []
        self.updated_in_place = False
        try:
            mcp_tool_names = await self._install_mcps(package, result)
            skill_ids = await self._install_skills(package, result)
            agent_ids = await self._install_agents(package, mcp_tool_names, skill_ids, result)
            await self._install_channels(package, agent_ids, result)
            await self._install_automations(package, agent_ids, result)
            await self._install_policies(package, agent_ids, result)
            await self._record_orphans(package, result)
        except Exception:
            if self.updated_in_place:
                logger.warning(
                    "Redeploy of bundle '%s' failed after updating in place; keeping what it created",
                    package.name,
                    exc_info=True,
                )
            await self._undo_created(unfinished_only=self.updated_in_place)
            raise
        return result

    def partial_result(self) -> InstallResult:
        """What a failed redeploy wrote, plus what earlier installs own that it never reached."""
        result = self.result.model_copy(deep=True)
        if self._prior is None:
            return result
        reached = {(e.kind, e.key) for e in result.entities}
        for ref in self._prior.owned_entities():
            if (ref.kind, ref.key) not in reached:
                result.entities.append(
                    ref.model_copy(
                        update={"fingerprint": self._prior.fingerprint(ref.kind, ref.key)}
                    )
                )
        return result

    async def _refuse_blocking_issues(self, package: Bundle, setup_values: dict[str, Any]) -> None:
        """Raise :class:`BundleValidationError` if analyze or setup blocks the bundle.

        The analyzer runs without workspace lookups: whether an entity already
        exists only decides reuse, never whether the bundle is installable. Which
        setup a redeploy needs depends on what it writes, which only the plan
        BundleService makes knows; a first install needs every required field.
        """
        preview = await BundleAnalyzer(prior=self._prior, setup_values=setup_values).analyze(
            package
        )
        block = preview.block_issues
        if block:
            raise BundleValidationError(
                f"package is not installable: {block[0].message}"
                + (f" (and {len(block) - 1} more)" if len(block) > 1 else ""),
                issues=block,
            )
        setup_block = required_setup_errors(package, self._values) if self._prior is None else []
        if setup_block:
            raise BundleValidationError(
                "package is not installable: missing required setup", issues=setup_block
            )
        secret_block = context_secret_errors(package, self._values)
        if secret_block:
            raise BundleValidationError(
                f"package is not installable: {secret_block[0].message}", issues=secret_block
            )

    async def _record_orphans(self, package: Bundle, result: InstallResult) -> None:
        """Keep entities dropped from the bundle on record; v1 never deletes them."""
        if self._prior is None:
            return
        for ref in self._prior.owned_entities():
            if any(i.key == ref.key for i in bundle_entities(package, ref.kind)):
                continue
            if ref.id is None or await self.get_entity(ref.kind, ref.id) is None:
                continue
            result.entities.append(
                InstalledEntity(
                    kind=ref.kind,
                    key=ref.key,
                    name=ref.name,
                    action=InstallAction.ORPHANED,
                    id=ref.id,
                    detail=ORPHANED_DETAIL,
                    fingerprint=self._applied(ref.kind, ref.key),
                )
            )

    # -- MCP ----------------------------------------------------------------

    async def _install_mcps(self, package: Bundle, result: InstallResult) -> dict[str, str]:
        """Returns {package mcp key -> instance name to use in agent tools}."""
        tool_names: dict[str, str] = {}
        for mcp in package.mcps:
            reason = mcp_is_unsupported(mcp)
            if reason:
                result.entities.append(self._skipped(EntityKind.MCP, mcp.key, mcp.name, reason))
                continue

            owned = await self._owned(EntityKind.MCP, mcp.key)
            if owned is not None:
                instance_id, instance = owned
                tool_names[mcp.key] = instance.name
                changed = self._needs_update(EntityKind.MCP, mcp, [])
                # Not applied, so the record keeps what was: the change is reported until it is.
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.MCP,
                        key=mcp.key,
                        name=instance.name,
                        action=InstallAction.UNCHANGED,
                        id=str(instance_id),
                        detail=MCP_NOT_APPLIED if changed else None,
                        fingerprint=(
                            self._applied(EntityKind.MCP, mcp.key)
                            if changed
                            else self._fingerprint(mcp)
                        ),
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

            instance = await self._create_mcp(package, mcp)
            tool_names[mcp.key] = mcp.name
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.MCP,
                    key=mcp.key,
                    name=mcp.name,
                    action=InstallAction.CREATED,
                    id=str(instance.id),
                    fingerprint=self._fingerprint(mcp),
                )
            )
        return tool_names

    async def _create_mcp(self, package: Bundle, mcp: BundleMcp) -> Any:
        """Create the instance: from its catalog spec, or from a spec this install creates."""
        from agentarea_mcp.application.validation_service import MCPValidationError
        from agentarea_mcp.schemas.dto import MCPServerCreate, MCPServerInstanceCreate
        from agentarea_mcp.transport_spec import server_transport

        if mcp.catalog is not None:
            spec = await self._mcp_server_service.get_catalog_server(mcp.catalog)
            if spec is None:
                raise BundleValidationError(
                    f"mcp '{mcp.key}' names catalog server '{mcp.catalog}', which the catalog "
                    "does not have"
                )
            spec_id = spec.id
            try:
                transport = server_transport(spec).value
            except ValueError as exc:
                raise BundleValidationError(
                    f"mcp '{mcp.key}' names catalog server '{mcp.catalog}', which declares "
                    "no transport"
                ) from exc
        else:
            json_spec = mcp.json_spec or {}
            fields = _transport_fields(json_spec, self._values)
            transport = fields["type"]
            spec_kwargs: dict[str, Any] = {
                "name": mcp.name,
                "description": f"Imported from package '{package.name}'",
                "env_schema": self._build_env_schema(mcp, package),
                "json_spec": fields,
            }
            if transport == "command":
                command = fields.get("command")
                spec_kwargs["cmd"] = [command, *fields.get("args", [])] if command else None
            elif transport == "docker":
                spec_kwargs["docker_image_url"] = fields.get("image")
            elif transport == "url":
                spec_kwargs["remote_url"] = fields.get("endpoint_url")
            created_spec = await self._mcp_server_service.create_mcp_server(
                MCPServerCreate(**spec_kwargs)
            )
            self._track(
                f"MCP server spec '{mcp.name}'",
                lambda spec_id=created_spec.id: self._mcp_server_service.delete_mcp_server(spec_id),
            )
            spec_id = created_spec.id

        target = "headers" if transport == "url" else "environment"
        resolved = {
            env_name: value
            for env_name, ref in mcp.bindings.items()
            if not setup_refs(value := resolve_placeholders(ref, self._values))
        }
        instance_json: dict[str, Any] = {}
        for field in ("environment", "headers"):
            values = _plain_config(mcp.json_spec, field)
            if field == target:
                values.update(resolved)
            if values:
                instance_json[field] = values

        context_secret = (
            resolve_placeholders(mcp.context_secret, self._values) if mcp.context_secret else None
        )
        try:
            instance = await self._mcp_instance_service.create_instance(
                MCPServerInstanceCreate(
                    name=mcp.name,
                    server_spec_id=spec_id,
                    json_spec=instance_json,
                    context_secret=context_secret,
                )
            )
        except MCPValidationError as exc:
            raise BundleValidationError(
                f"MCP '{mcp.key}' was refused: {'; '.join(exc.errors)}"
            ) from exc
        if instance is None:
            raise BundleInstallError(f"failed to create MCP instance '{mcp.name}'")
        copied_spec_id = getattr(instance, "server_spec_id", None)
        if mcp.catalog is not None and copied_spec_id and str(copied_spec_id) != str(spec_id):
            # Connecting a catalog spec copies it into the workspace; the copy goes with it.
            self._track(
                f"MCP server spec copy '{mcp.name}'",
                lambda copy_id=copied_spec_id: self._mcp_server_service.delete_mcp_server(
                    UUID(str(copy_id))
                ),
            )
        self._track(
            f"MCP instance '{mcp.name}'",
            lambda instance_id=instance.id: self._mcp_instance_service.delete_instance(instance_id),
        )
        return instance

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
        from agentarea_agents.schemas.skills_dto import SkillEditMetadata

        skill_ids: dict[str, UUID] = {}
        for skill in package.skills:
            owned = await self._owned(EntityKind.SKILL, skill.key)
            if owned is not None:
                skill_id, _ = owned
                skill_ids[skill.key] = skill_id
                action = InstallAction.UNCHANGED
                detail = None
                fingerprint = self._fingerprint(skill)
                if self._needs_update(EntityKind.SKILL, skill, []):
                    if skill.source_type == "github":
                        detail = GITHUB_SKILL_NOT_APPLIED
                        fingerprint = self._applied(EntityKind.SKILL, skill.key) or fingerprint
                    else:
                        await self._authorize_update(EntityKind.SKILL, skill.key, skill_id)
                        await self._write_skill_files(skill_id, skill)
                        self.updated_in_place = True
                        await self._skill_service.update(
                            skill_id, SkillEditMetadata(name=skill.name)
                        )
                        action = InstallAction.UPDATED
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.SKILL,
                        key=skill.key,
                        name=skill.name,
                        action=action,
                        id=str(skill_id),
                        detail=detail,
                        fingerprint=fingerprint,
                    )
                )
                continue

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

            created = await self._create_skill(skill)
            self._track(
                f"skill '{skill.name}'",
                lambda skill_id=created.id: self._skill_service.delete(skill_id),
            )
            skill_ids[skill.key] = created.id
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.SKILL,
                    key=skill.key,
                    name=skill.name,
                    action=InstallAction.CREATED,
                    id=str(created.id),
                    fingerprint=self._fingerprint(skill),
                )
            )
        return skill_ids

    async def _create_skill(self, skill: BundleSkill) -> Any:
        from agentarea_agents.infrastructure.github_skill_importer import (
            GitHubSkillImporterError,
        )
        from agentarea_agents.schemas.skills_dto import (
            SkillCreateFromContent,
            SkillImportFromGithub,
        )

        if skill.source_type == "github":
            try:
                return await self._skill_service.create_from_github(
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
        try:
            if skill.source_type == "files":
                return await self._skill_service.create_from_zip(
                    _skill_zip(skill.files or {}), name=skill.name
                )
            return await self._skill_service.create_from_content(
                SkillCreateFromContent(
                    content=skill.content or "", name=skill.name, description=None
                )
            )
        except ValueError as exc:
            raise BundleValidationError(
                f"skill '{skill.key}' is not a valid SKILL.md: {exc}"
            ) from exc

    async def _write_skill_files(self, skill_id: UUID, skill: BundleSkill) -> None:
        """Store the skill's files as its next package version."""
        # The folder is the skill's whole package: a file it no longer holds goes.
        files = (
            skill.files or {} if skill.source_type == "files" else {"SKILL.md": skill.content or ""}
        )
        try:
            await self._skill_service.replace_package_from_files(skill_id, files)
        except ValueError as exc:
            raise BundleValidationError(
                f"skill '{skill.key}' is not a valid SKILL.md: {exc}"
            ) from exc

    # -- agents -------------------------------------------------------------

    async def _install_agents(
        self,
        package: Bundle,
        mcp_tool_names: dict[str, str],
        skill_ids: dict[str, UUID],
        result: InstallResult,
    ) -> dict[str, UUID]:
        """Returns {package agent key -> agent id}."""
        from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
        from agentarea_agents.schemas.import_export import CodeToolConfig, McpToolConfig, ToolConfig

        agent_ids: dict[str, UUID] = {}
        for agent in package.agents:
            tools: list[ToolConfig] = [
                *(CodeToolConfig(name=name) for name in agent.toolsets),
                *(
                    McpToolConfig(name=mcp_tool_names[ref])
                    for ref in agent.mcps
                    if ref in mcp_tool_names  # unsupported MCPs were skipped
                ),
            ]
            attached_skill_ids = [skill_ids[ref] for ref in agent.skills if ref in skill_ids]
            model_id = resolve_placeholders(agent.model or "", self._values)

            owned = await self._owned(EntityKind.AGENT, agent.key)
            if owned is not None:
                agent_id, _ = owned
                agent_ids[agent.key] = agent_id
                action = InstallAction.UNCHANGED
                depends_on = [
                    *((EntityKind.MCP, ref) for ref in agent.mcps),
                    *((EntityKind.SKILL, ref) for ref in agent.skills),
                ]
                if self._needs_update(EntityKind.AGENT, agent, depends_on):
                    await self._authorize_update(EntityKind.AGENT, agent.key, agent_id)
                    updated = await self._agent_service.update_agent(
                        agent_id,
                        AgentUpdate(
                            name=agent.name,
                            description=agent.description,
                            instruction=agent.instruction,
                            model_id=model_id,
                            tools=tools,
                            skill_ids=attached_skill_ids,
                        ),
                    )
                    if updated is None:
                        raise BundleInstallError(f"agent '{agent.key}' disappeared mid-update")
                    self.updated_in_place = True
                    action = InstallAction.UPDATED
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AGENT,
                        key=agent.key,
                        name=agent.name,
                        action=action,
                        id=str(agent_id),
                        fingerprint=self._fingerprint(agent),
                    )
                )
                continue

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

            created = await self._agent_service.create_agent(
                AgentCreate(
                    name=agent.name,
                    description=agent.description,
                    instruction=agent.instruction,
                    model_id=model_id,
                    tools=tools,
                    skill_ids=attached_skill_ids or None,
                )
            )
            self._track(
                f"agent '{agent.name}'",
                lambda agent_id=created.id: self._agent_service.delete_agent(agent_id),
            )
            agent_ids[agent.key] = created.id
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.AGENT,
                    key=agent.key,
                    name=agent.name,
                    action=InstallAction.CREATED,
                    id=str(created.id),
                    fingerprint=self._fingerprint(agent),
                )
            )
        return agent_ids

    # -- channels -----------------------------------------------------------

    async def _install_channels(
        self, package: Bundle, agent_ids: dict[str, UUID], result: InstallResult
    ) -> None:
        """Provision messaging channels (e.g. Telegram) as a stream, its webhook source and a trigger.

        A channel becomes a stream named after it, fed by a webhook source of the
        channel's catalog type, with a stream trigger running its agent: a
        message to the bot creates a task, and the reply goes back on the same
        chat. The source's credentials are stored at
        ``channel_cred:{type}:{source_id}``; credentials the catalog entry
        issues are generated. A redeploy rewrites only the credentials supplied
        to it, merged into the stored ones, or every one it resolves when none
        were stored. Imported disabled by default.
        """
        from agentarea_streams.application.source_credentials import credential_secret_name
        from agentarea_streams.domain.enums import SourceKind
        from agentarea_streams.infrastructure.catalog_source_types import (
            CatalogSourceTypeRepository,
        )
        from agentarea_triggers.schemas.dto import TriggerCreate, TriggerUpdate

        streams = self._trigger_service.stream_service
        catalog = CatalogSourceTypeRepository(streams.repository_factory.session)
        existing_names = {t.name for t in await self._trigger_repository.list_all()}
        for channel in package.channels:
            name = trigger_name(package, channel.key)
            agent_id = agent_ids.get(channel.agent)
            if agent_id is None:
                result.entities.append(
                    self._skipped(
                        EntityKind.CHANNEL,
                        channel.key,
                        name,
                        f"agent '{channel.agent}' was not created",
                    )
                )
                continue
            owned = await self._owned(EntityKind.CHANNEL, channel.key)
            if owned is not None:
                trigger_id, trigger = owned
                depends_on = [(EntityKind.AGENT, channel.agent)]
                update = self._needs_update(EntityKind.CHANNEL, channel, depends_on)
                source = await self.channel_source(trigger)
                credentials = await self._channel_rewrite(channel, source)
                if update or credentials:
                    await self._authorize_update(EntityKind.CHANNEL, channel.key, trigger_id)
                if update:
                    await self._trigger_service.update_trigger_from_payload(
                        trigger_id,
                        TriggerUpdate(
                            description=channel.name,
                            agent_id=agent_id,
                            task_parameters={"text": channel.prompt},
                        ),
                    )
                    self.updated_in_place = True
                    if self._enabled_changed(EntityKind.CHANNEL, channel):
                        await self._set_trigger_enabled(trigger_id, trigger, channel.enabled)
                if credentials and source is not None:
                    await self._secret_manager.set_secret(
                        credential_secret_name(source.webhook_type, source.credential_key),
                        json.dumps(credentials),
                    )
                    self.updated_in_place = True
                action = InstallAction.UPDATED if update or credentials else InstallAction.UNCHANGED
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.CHANNEL,
                        key=channel.key,
                        name=name,
                        action=action,
                        id=str(trigger_id),
                        detail=f"{channel.type} · enabled={channel.enabled}",
                        fingerprint=self._fingerprint(channel),
                    )
                )
                continue
            if name in existing_names:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.CHANNEL,
                        key=channel.key,
                        name=name,
                        action=InstallAction.REUSED,
                    )
                )
                continue
            slug = "generic_webhook" if channel.type == "generic" else channel.type
            entry = await catalog.get(slug)
            if entry is None:
                raise BundleInstallError(f"channel type {channel.type!r} is not in the catalog")

            credentials: dict[str, Any] = channel_credentials(channel, self._values)
            for field in entry.credentials:
                if field.issued and field.key not in credentials:
                    credentials[field.key] = secrets.token_urlsafe(32)

            stream = await streams.create_stream(name=name, description=channel.name)
            self._track(
                f"channel stream of '{name}'",
                lambda stream_id=stream.id: streams.delete_stream(stream_id),
            )
            source = await streams.add_source(
                stream_id=stream.id,
                kind=SourceKind.WEBHOOK,
                source_type=entry.slug,
                webhook_config={},
                event_templates=None,
            )
            if self._secret_manager is not None:
                secret_name = credential_secret_name(entry.slug, source.id)
                await self._secret_manager.set_secret(secret_name, json.dumps(credentials))
                self._track(
                    f"channel credential of '{name}'",
                    lambda name=secret_name, store=self._secret_manager: store.delete_secret(name),
                )

            dto = TriggerCreate(
                name=name,
                description=channel.name,
                agent_id=agent_id,
                trigger_type="stream",
                stream_id=stream.id,
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
            self._track(
                f"channel trigger '{name}'",
                lambda trigger_id=trigger.id: self._trigger_service.delete_trigger(trigger_id),
            )
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.CHANNEL,
                    key=channel.key,
                    name=name,
                    action=InstallAction.CREATED,
                    id=str(trigger.id),
                    detail=f"{channel.type} · enabled={channel.enabled}",
                    fingerprint=self._fingerprint(channel),
                )
            )

    async def channel_source(self, trigger: Any) -> Any | None:
        """The webhook source feeding a channel trigger's stream."""
        stream_id = getattr(trigger, "stream_id", None)
        if stream_id is None:
            return None
        sources = await self._trigger_service.stream_service.list_sources(stream_id)
        return next((s for s in sources if s.webhook_type and s.credential_key), None)

    async def channel_credentials_stored(self, source: Any | None) -> dict[str, Any]:
        """The credentials stored for a channel's source, as written; empty when none."""
        from agentarea_streams.application.source_credentials import credential_secret_name

        if self._secret_manager is None or source is None:
            return {}
        raw = await self._secret_manager.get_secret(
            credential_secret_name(source.webhook_type, source.credential_key)
        )
        stored = json.loads(raw) if raw else {}
        return stored if isinstance(stored, dict) else {}

    async def _channel_rewrite(self, channel: BundleChannel, source: Any | None) -> dict[str, Any]:
        """Credentials a redeploy stores: the supplied ones merged in, or all when none were stored."""
        if self._secret_manager is None or source is None or not channel.bindings:
            return {}
        stored = await self.channel_credentials_stored(source)
        bound = set(channel.bindings)
        unfinished = not (bound & set(stored))
        rewrite = channel_credentials(channel, self._values, None if unfinished else self._supplied)
        return {**stored, **rewrite} if rewrite else {}

    def _enabled_changed(self, kind: EntityKind, spec: Any) -> bool:
        """The file changed ``enabled``; otherwise a toggle made in the workspace stands."""
        before = self._prior.spec(kind, spec.key) if self._prior else None
        return before is None or before.enabled != spec.enabled

    async def _set_trigger_enabled(self, trigger_id: UUID, trigger: Any, enabled: bool) -> None:
        """Toggle through the service so a cron schedule is paused or resumed with it."""
        if trigger.is_active == enabled:
            return
        if enabled:
            await self._trigger_service.enable_trigger(trigger_id)
        else:
            await self._trigger_service.disable_trigger(trigger_id)

    # -- automations --------------------------------------------------------

    async def _install_automations(
        self, package: Bundle, agent_ids: dict[str, UUID], result: InstallResult
    ) -> None:
        from agentarea_triggers.schemas.dto import TriggerUpdate

        existing_names = {t.name for t in await self._trigger_repository.list_all()}
        for auto in package.automations:
            name = trigger_name(package, auto.key)
            agent_id = agent_ids.get(auto.agent)
            if agent_id is None:
                result.entities.append(
                    self._skipped(
                        EntityKind.AUTOMATION,
                        auto.key,
                        name,
                        f"agent '{auto.agent}' was not created",
                    )
                )
                continue
            owned = await self._owned(EntityKind.AUTOMATION, auto.key)
            if owned is not None:
                trigger_id, trigger = owned
                action = InstallAction.UNCHANGED
                depends_on = [(EntityKind.AGENT, auto.agent)]
                if self._needs_update(EntityKind.AUTOMATION, auto, depends_on):
                    await self._authorize_update(EntityKind.AUTOMATION, auto.key, trigger_id)
                    await self._trigger_service.update_trigger_from_payload(
                        trigger_id,
                        TriggerUpdate(
                            description=f"Runs {auto.cron} ({auto.timezone})",
                            agent_id=agent_id,
                            cron_expression=auto.cron,
                            timezone=auto.timezone,
                            task_parameters={"text": auto.prompt},
                        ),
                    )
                    self.updated_in_place = True
                    if self._enabled_changed(EntityKind.AUTOMATION, auto):
                        await self._set_trigger_enabled(trigger_id, trigger, auto.enabled)
                    action = InstallAction.UPDATED
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AUTOMATION,
                        key=auto.key,
                        name=name,
                        action=action,
                        id=str(trigger_id),
                        detail=f"enabled={auto.enabled}",
                        fingerprint=self._fingerprint(auto),
                    )
                )
                continue
            if name in existing_names:
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.AUTOMATION,
                        key=auto.key,
                        name=name,
                        action=InstallAction.REUSED,
                    )
                )
                continue

            trigger = await self._trigger_service.create_trigger(
                automation_trigger(package, auto, agent_id, self._user_context)
            )
            self._track(
                f"automation trigger '{name}'",
                lambda trigger_id=trigger.id: self._trigger_service.delete_trigger(trigger_id),
            )
            result.entities.append(
                InstalledEntity(
                    kind=EntityKind.AUTOMATION,
                    key=auto.key,
                    name=name,
                    action=InstallAction.CREATED,
                    id=str(trigger.id),
                    detail=f"enabled={auto.enabled}",
                    fingerprint=self._fingerprint(auto),
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
                        self._skipped(
                            EntityKind.POLICY,
                            policy.key,
                            policy.key,
                            f"agent '{policy.subject}' was not created",
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
                    self._skipped(
                        EntityKind.POLICY, policy.key, policy.key, f"would never enforce: {exc}"
                    )
                )
                continue

            owned = await self._owned(EntityKind.POLICY, policy.key)
            if owned is not None:
                rule_id, _ = owned
                action = InstallAction.UNCHANGED
                depends_on = [(EntityKind.AGENT, policy.subject)]
                if self._needs_update(EntityKind.POLICY, policy, depends_on):
                    await self._authorize_update(EntityKind.POLICY, policy.key, rule_id)
                    fields: dict[str, Any] = {
                        "subject_type": rule.subject_type,
                        "subject_id": rule.subject_id,
                        "target": rule.target,
                        "effect": rule.effect,
                        "params": rule.params,
                        "condition": rule.condition,
                        "priority": rule.priority,
                    }
                    if self._enabled_changed(EntityKind.POLICY, policy):
                        fields["enabled"] = rule.enabled
                    updated = await self._governance_service.update_rule(rule_id=rule_id, **fields)
                    if updated is None:
                        raise BundleInstallError(f"policy '{policy.key}' disappeared mid-update")
                    self.updated_in_place = True
                    action = InstallAction.UPDATED
                result.entities.append(
                    InstalledEntity(
                        kind=EntityKind.POLICY,
                        key=policy.key,
                        name=policy.key,
                        action=action,
                        id=str(rule_id),
                        detail=f"{policy.effect} {policy.target} on {policy.subject}",
                        fingerprint=self._fingerprint(policy),
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
            if created.id:
                self._track(
                    f"policy '{policy.key}'",
                    lambda rule_id=created.id: self._governance_service.delete_rule(
                        rule_id=rule_id
                    ),
                )
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
                    fingerprint=self._fingerprint(policy),
                )
            )
