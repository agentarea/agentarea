"""BundleService: analyze + install entry point.

Wires the pure analyzer/installer to the workspace's repositories and domain
services, and records an ``InstalledBundle`` row: the ids an install created or
reused, which is how the next install of the same bundle finds its own entities
(and how the preview says which already exist).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from agentarea_common.agent_status import AgentStatus

from agentarea_bundles.application.analyzer import (
    BundleAnalyzer,
    parse_bundle,
)
from agentarea_bundles.application.installer import BundleInstaller
from agentarea_bundles.domain.models import InstalledBundle
from agentarea_bundles.infrastructure.repository import InstalledBundleRepository
from agentarea_bundles.schemas.bundle import Bundle
from agentarea_bundles.schemas.preview import EntityKind, ImportPreview
from agentarea_bundles.schemas.result import InstallAction, InstallResult

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
        package = await asyncio.to_thread(parse_bundle, text)
        return await self.analyze_bundle(package)

    async def analyze_bundle(self, package: Bundle) -> ImportPreview:
        installed = await self._installed_ids(package.name)
        analyzer = BundleAnalyzer(existence=_InstalledBefore(self, package.name, installed))
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
            secret_manager=self._secret_manager,
            installed=await self._installed_ids(package.name),
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

    async def _installed_ids(self, bundle_name: str) -> dict[tuple[str, str], str]:
        """{(entity kind, bundle key) -> id} the last install of this bundle recorded."""
        record = await self._bundle_repository.get_by_name(bundle_name)
        entities = (record.install_result or {}).get("entities") if record else None
        installed: dict[tuple[str, str], str] = {}
        for entity in entities or []:
            if not isinstance(entity, dict) or not entity.get("id"):
                continue
            if entity.get("action") in (InstallAction.CREATED, InstallAction.REUSED):
                installed[(str(entity.get("kind")), str(entity.get("key")))] = str(entity["id"])
        return installed

    async def _recorded(self, installed: dict[tuple[str, str], str], kind: EntityKind, key: str):
        recorded = installed.get((kind.value, key))
        if not recorded:
            return None
        try:
            entity_id = UUID(recorded)
        except ValueError:
            return None
        if kind is EntityKind.AGENT:
            agent = await self._agent_repository.get(entity_id)
            return agent if agent is not None and agent.status != AgentStatus.ARCHIVED else None
        if kind is EntityKind.MCP:
            return await self._mcp_instance_service.get(entity_id)
        if kind is EntityKind.SKILL:
            return await self._skill_repository.get(entity_id)
        return None


class _InstalledBefore:
    """Preview status: what an earlier install of this bundle put here and is still here."""

    def __init__(
        self, service: BundleService, bundle_name: str, installed: dict[tuple[str, str], str]
    ) -> None:
        self._service = service
        self._bundle_name = bundle_name
        self._installed = installed

    async def agent_exists(self, key: str) -> bool:
        return await self._service._recorded(self._installed, EntityKind.AGENT, key) is not None

    async def mcp_instance_exists(self, key: str) -> bool:
        return await self._service._recorded(self._installed, EntityKind.MCP, key) is not None

    async def skill_exists(self, key: str) -> bool:
        return await self._service._recorded(self._installed, EntityKind.SKILL, key) is not None

    async def trigger_exists(self, key: str, agent_key: str) -> bool:
        agent = await self._service._recorded(self._installed, EntityKind.AGENT, agent_key)
        if agent is None:
            return False
        name = f"{self._bundle_name}:{key}"
        recorded = self._installed.get((EntityKind.AUTOMATION.value, key))
        triggers = await self._service._trigger_repository.list_all()
        return any(
            t.name == name and t.agent_id == agent.id and recorded in (None, str(t.id))
            for t in triggers
        )
