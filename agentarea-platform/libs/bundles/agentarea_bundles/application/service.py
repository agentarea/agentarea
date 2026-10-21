"""BundleService: analyze + install entry point.

Wires the pure analyzer/installer to the workspace's repositories and domain
services, implements the existence checker for preview status, and records an
``InstalledBundle`` row for provenance/idempotency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from agentarea_bundles.application.analyzer import (
    BundleAnalyzer,
    CatalogMcp,
    PriorInstall,
    context_secret_errors,
    effective_setup,
    parse_bundle,
    required_setup_errors,
)
from agentarea_bundles.application.folder import load_folder
from agentarea_bundles.application.installer import (
    BundleInstaller,
    BundleValidationError,
    automation_trigger,
)
from agentarea_bundles.domain.models import InstalledBundle
from agentarea_bundles.infrastructure.repository import InstalledBundleRepository
from agentarea_bundles.schemas.bundle import Bundle, BundleAutomation
from agentarea_bundles.schemas.preview import (
    EntityKind,
    EntityStatus,
    ImportPreview,
    IssueSeverity,
    PreviewIssue,
)
from agentarea_bundles.schemas.result import InstallResult

logger = logging.getLogger(__name__)


# The resource type each kind's update route checks edit permission on.
_RESOURCE_TYPES = {
    EntityKind.SKILL: "skill",
    EntityKind.AGENT: "agent",
    EntityKind.CHANNEL: "trigger",
    EntityKind.AUTOMATION: "trigger",
}


def _id_of(entity: Any) -> str | None:
    return None if entity is None else str(entity.id)


class BundleService:
    """Analyze package source and install canonical packages into a workspace."""

    def __init__(
        self,
        *,
        repository_factory: Any,
        agent_service: Any,
        mcp_server_service: Any,
        mcp_instance_service: Any,
        skill_service: Any,
        trigger_service: Any,
        secret_manager: Any = None,
    ) -> None:
        self._repository_factory = repository_factory
        self._user_context = repository_factory.user_context
        self._agent_service = agent_service
        self._mcp_server_service = mcp_server_service
        self._mcp_instance_service = mcp_instance_service
        self._skill_service = skill_service
        self._trigger_service = trigger_service
        self._secret_manager = secret_manager
        self._catalog_mcps: dict[str, CatalogMcp | None] = {}

        # Repositories for existence checks / idempotency.
        from agentarea_agents.infrastructure.repository import AgentRepository
        from agentarea_agents.infrastructure.skill_repository import SkillRepository
        from agentarea_governance.application.service import GovernancePolicyService
        from agentarea_triggers.infrastructure.repository import TriggerRepository

        self._agent_repository = repository_factory.create_repository(AgentRepository)
        self._skill_repository = repository_factory.create_repository(SkillRepository)
        self._trigger_repository = repository_factory.create_repository(TriggerRepository)
        self._bundle_repository = repository_factory.create_repository(InstalledBundleRepository)
        # Governance service owns PolicyRule creation; built from the same factory.
        self._governance_service = GovernancePolicyService(repository_factory)

    # -- analyze ------------------------------------------------------------

    async def analyze_text(
        self, text: str, setup_values: dict[str, Any] | None = None
    ) -> ImportPreview:
        """Parse source text into a package and produce an import preview."""
        package = await asyncio.to_thread(parse_bundle, text)
        return await self.analyze_bundle(package, setup_values)

    async def analyze_files(
        self, files: dict[str, str], setup_values: dict[str, Any] | None = None
    ) -> ImportPreview:
        """Load an agent folder into a package and produce an import preview."""
        package, folder_issues = await asyncio.to_thread(load_folder, files)
        preview = await self.analyze_bundle(package, setup_values)
        preview.issues = [*folder_issues, *preview.issues]
        return preview

    async def analyze_bundle(
        self, package: Bundle, setup_values: dict[str, Any] | None = None
    ) -> ImportPreview:
        prior, unreadable = await self._prior(package.name)
        if unreadable is not None:
            return ImportPreview(
                bundle=package, setup=package.setup, issues=[unreadable], installable=False
            )
        analyzer = BundleAnalyzer(
            existence=self, prior=prior, setup_values=setup_values, checks=self
        )
        return await analyzer.analyze(package)

    async def _prior(self, name: str) -> tuple[PriorInstall | None, PreviewIssue | None]:
        """The last install of this package in the workspace, the base a redeploy diffs on.

        A stored record that no longer validates is a blocking issue, never "no
        prior install": that would create everything it owns a second time.
        """
        record = await self._bundle_repository.get_by_name(name)
        if record is None:
            return None, None
        try:
            return PriorInstall.from_record(record.canonical, record.install_result), None
        except ValidationError as exc:
            logger.error("Stored install of bundle '%s' no longer validates", name, exc_info=True)
            return None, PreviewIssue(
                severity=IssueSeverity.BLOCK,
                message=(
                    f"the record of the last install of '{name}' no longer validates "
                    f"({exc.error_count()} errors), so what it created cannot be matched; "
                    "nothing is planned"
                ),
            )

    # -- install ------------------------------------------------------------

    async def install(self, package: Bundle, setup_values: dict[str, Any]) -> InstallResult:
        """Plan, refuse anything the plan blocks, then write.

        All or nothing for what the install creates: a failure removes it again
        and leaves the record of the last install as it was, so the next deploy
        plans the same changes.
        """
        prior, unreadable = await self._prior(package.name)
        if unreadable is not None:
            raise BundleValidationError(unreadable.message, issues=[unreadable])
        analyzer = BundleAnalyzer(
            existence=self, prior=prior, setup_values=setup_values, checks=self
        )
        preview = await analyzer.analyze(package)
        values = effective_setup(package, setup_values, prior)
        block = [
            *preview.block_issues,
            *required_setup_errors(package, values, analyzer.needed_setup),
            *context_secret_errors(package, values),
        ]
        if block:
            raise BundleValidationError(
                f"package is not installable: {block[0].message}"
                + (f" (and {len(block) - 1} more)" if len(block) > 1 else ""),
                issues=block,
            )

        approved = {
            (e.kind, e.key) for e in preview.entities if e.status is EntityStatus.WILL_UPDATE
        }
        writes_policies = any(
            e.kind is EntityKind.POLICY
            and e.status in (EntityStatus.WILL_CREATE, EntityStatus.WILL_UPDATE)
            for e in preview.entities
        )
        installer = self._installer()
        try:
            result = await installer.install(
                package,
                setup_values,
                prior=prior,
                approved_updates=approved,
                writes_policies=writes_policies,
            )
        except Exception:
            if installer.updated_in_place:
                await self._record_partial(package, installer)
            raise
        result.installed_bundle_id = await self._record(package, result)
        return result

    async def _record_partial(self, package: Bundle, installer: BundleInstaller) -> None:
        """Keep ownership of what a redeploy wrote before it failed, so the next one finishes it."""
        try:
            await self._repository_factory.session.rollback()
            await self._record(package, installer.partial_result(), status="failed")
        except Exception:
            logger.exception("Could not record the failed redeploy of bundle '%s'", package.name)

    def _installer(self) -> BundleInstaller:
        return BundleInstaller(
            mcp_server_service=self._mcp_server_service,
            mcp_instance_service=self._mcp_instance_service,
            skill_service=self._skill_service,
            skill_repository=self._skill_repository,
            agent_service=self._agent_service,
            agent_repository=self._agent_repository,
            trigger_service=self._trigger_service,
            trigger_repository=self._trigger_repository,
            governance_service=self._governance_service,
            user_context=self._user_context,
            may_edit=self.may_edit,
            secret_manager=self._secret_manager,
        )

    async def _record(
        self, package: Bundle, result: InstallResult, *, status: str = "installed"
    ) -> str:
        """Upsert the InstalledBundle provenance row (idempotent by name)."""
        existing = await self._bundle_repository.get_by_name(package.name)
        install_result = result.model_dump(mode="json")
        if existing:
            updated = await self._bundle_repository.update(
                existing.id,
                display_name=package.display_name,
                description=package.description,
                schema_version=package.schema_version,
                status=status,
                canonical=package.model_dump(mode="json"),
                install_result=install_result,
            )
            return str((updated or existing).id)
        created: InstalledBundle = await self._bundle_repository.create(
            name=package.name,
            display_name=package.display_name,
            description=package.description,
            schema_version=package.schema_version,
            status=status,
            canonical=package.model_dump(mode="json"),
            install_result=install_result,
        )
        return str(created.id)

    # -- ExistenceChecker ---------------------------------------------------

    async def find_agent(self, name: str) -> str | None:
        return _id_of(await self._agent_repository.get_agent_by_name(name))

    async def find_mcp_instance(self, name: str) -> str | None:
        return _id_of(await self._mcp_instance_service.get_by_name(name))

    async def find_skill(self, name: str) -> str | None:
        return _id_of(await self._skill_repository.get_by_name(name))

    async def find_trigger(self, name: str) -> str | None:
        triggers = await self._trigger_repository.list_all()
        return next((str(t.id) for t in triggers if t.name == name), None)

    async def ref_exists(self, kind: EntityKind, entity_id: str) -> bool:
        return await self._installer().get_entity(kind, entity_id) is not None

    async def channel_credential_keys(self, entity_id: str) -> set[str] | None:
        if self._secret_manager is None:
            return None
        installer = self._installer()
        trigger = await self._trigger_service.get_trigger(UUID(entity_id))
        source = await installer.channel_source(trigger) if trigger else None
        if source is None:
            return None
        return set(await installer.channel_credentials_stored(source))

    # -- DeployChecks -------------------------------------------------------

    async def catalog_mcp(self, catalog_id: str) -> CatalogMcp | None:
        from agentarea_mcp.transport_spec import server_transport

        if catalog_id not in self._catalog_mcps:
            spec = await self._mcp_server_service.get_catalog_server(catalog_id)
            found = None
            if spec is not None:
                try:
                    transport: str | None = server_transport(spec).value
                except ValueError:
                    logger.warning(
                        "Catalog server '%s' declares no transport", catalog_id, exc_info=True
                    )
                    transport = None
                found = CatalogMcp(spec_id=str(spec.id), transport=transport)
            self._catalog_mcps[catalog_id] = found
        return self._catalog_mcps[catalog_id]

    async def agent_problem(self, model_id: str, toolsets: list[str]) -> str | None:
        from agentarea_agents.application.agent_service import InvalidModelIdError
        from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata

        known = get_code_tools_metadata()
        unknown = [name for name in toolsets if name not in known]
        if unknown:
            return f"unknown toolset(s): {', '.join(unknown)}"
        try:
            await self._agent_service.validate_config(
                model_id, [{"type": "code", "name": name} for name in toolsets]
            )
        except InvalidModelIdError as exc:
            return str(exc)
        return None

    async def automation_problem(self, package: Bundle, automation: BundleAutomation) -> str | None:
        from agentarea_triggers.logging_utils import TriggerValidationError

        # The agent may not exist yet; the configuration check never reads it.
        trigger = automation_trigger(package, automation, UUID(int=0), self._user_context)
        try:
            await self._trigger_service.validate_configuration(trigger)
        except TriggerValidationError as exc:
            return str(exc)
        return None

    async def may_edit(self, kind: EntityKind, entity_id: str) -> bool:
        """The per-object edit check the entity's own update route makes."""
        from agentarea_common.auth.permission import PermissionService
        from agentarea_common.di.container import resolve

        return await resolve(PermissionService).check(
            self._user_context.graph_subject, "edit", _RESOURCE_TYPES[kind], entity_id
        )
