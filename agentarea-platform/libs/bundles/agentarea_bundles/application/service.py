"""BundleService: analyze + install entry point.

Wires the pure analyzer/installer to the workspace's repositories and domain
services, implements the existence checker for preview status, and records an
``InstalledBundle`` row for provenance/idempotency.
"""

from __future__ import annotations

import logging
from typing import Any

from agentarea_bundles.application.analyzer import (
    BundleAnalyzer,
    parse_bundle,
)
from agentarea_bundles.application.installer import BundleInstaller
from agentarea_bundles.domain.models import InstalledBundle
from agentarea_bundles.infrastructure.repository import InstalledBundleRepository
from agentarea_bundles.schemas.bundle import Bundle
from agentarea_bundles.schemas.preview import ImportPreview
from agentarea_bundles.schemas.result import InstallResult

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._repository_factory = repository_factory
        self._user_context = repository_factory.user_context
        self._agent_service = agent_service
        self._mcp_server_service = mcp_server_service
        self._mcp_instance_service = mcp_instance_service
        self._skill_service = skill_service
        self._trigger_service = trigger_service

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

    async def analyze_text(self, text: str) -> ImportPreview:
        """Parse source text into a package and produce an import preview."""
        package = parse_bundle(text)
        return await self.analyze_bundle(package)

    async def analyze_bundle(self, package: Bundle) -> ImportPreview:
        analyzer = BundleAnalyzer(existence=self)
        return await analyzer.analyze(package)

    # -- install ------------------------------------------------------------

    async def install(self, package: Bundle, setup_values: dict[str, Any]) -> InstallResult:
        installer = BundleInstaller(
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
        )
        result = await installer.install(package, setup_values)
        result.installed_bundle_id = await self._record(package, result)
        return result

    async def _record(self, package: Bundle, result: InstallResult) -> str:
        """Upsert the InstalledBundle provenance row (idempotent by name)."""
        existing = await self._bundle_repository.get_by_name(package.name)
        install_result = result.model_dump(mode="json")
        if existing:
            updated = await self._bundle_repository.update(
                existing.id,
                display_name=package.display_name,
                description=package.description,
                schema_version=package.schema_version,
                status="installed",
                canonical=package.model_dump(mode="json"),
                install_result=install_result,
            )
            return str((updated or existing).id)
        created: InstalledBundle = await self._bundle_repository.create(
            name=package.name,
            display_name=package.display_name,
            description=package.description,
            schema_version=package.schema_version,
            status="installed",
            canonical=package.model_dump(mode="json"),
            install_result=install_result,
        )
        return str(created.id)

    # -- ExistenceChecker ---------------------------------------------------

    async def agent_exists(self, name: str) -> bool:
        return await self._agent_repository.get_agent_by_name(name) is not None

    async def mcp_instance_exists(self, name: str) -> bool:
        return await self._mcp_instance_service.get_by_name(name) is not None

    async def skill_exists(self, name: str) -> bool:
        return await self._skill_repository.get_by_name(name) is not None

    async def trigger_exists(self, name: str) -> bool:
        # Triggers are named "<package>:<key>"; match on suffix within workspace.
        triggers = await self._trigger_repository.list_all()
        return any(t.name.endswith(f":{name}") for t in triggers)
