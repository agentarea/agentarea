"""RegistriesToolset — browse and sync MCP/skill registries."""

import json
from uuid import UUID

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

from .base import platform_context, platform_read_context


def _build_registry_service(session, user_ctx):
    from agentarea_agents.infrastructure.skill_repository import SkillRepository
    from agentarea_mcp.infrastructure.repository import MCPServerRepository
    from agentarea_registry.application.service import RegistryService
    from agentarea_registry.infrastructure.repository import (
        RegistryItemRepository,
        RegistryRepository,
    )

    return RegistryService(
        RegistryRepository(session, user_ctx),
        RegistryItemRepository(session, user_ctx),
        MCPServerRepository(session, user_ctx),
        SkillRepository(session, user_ctx),
    )


def _registry_summary(r) -> dict:
    return {
        "id": str(r.id),
        "name": r.name,
        "registry_type": r.registry_type,
        "source_type": r.source_type,
        "source_url": r.source_url,
        "is_active": r.is_active,
        "item_count": r.item_count,
        "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
    }


def _item_summary(i) -> dict:
    return {
        "id": str(i.id),
        "registry_id": str(i.registry_id),
        "external_id": i.external_id,
        "name": i.name,
        "description": i.description,
        "version": i.version,
        "tags": i.tags or [],
        "installed_entity_id": str(i.installed_entity_id) if i.installed_entity_id else None,
        "update_available": i.update_available,
        "installed_version": i.installed_version,
    }


class RegistriesToolset(Toolset):
    """Browse, search, and sync registries (MCP servers and skills)."""

    @tool_method
    async def list_registries(
        self,
        active_only: bool = False,
        registry_type: str = "",
    ) -> str:
        """List registries configured in the workspace."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            registries = await service.list_registries(
                active_only=active_only,
                registry_type=registry_type or None,
            )
            return json.dumps([_registry_summary(r) for r in registries], default=str)

    @tool_method
    async def get_registry(self, registry_id: str) -> str:
        """Get details of a registry."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            registry = await service.get_registry(UUID(registry_id))
            if not registry:
                return json.dumps({"error": "Registry not found"})
            return json.dumps(_registry_summary(registry), default=str)

    @tool_method
    async def list_items(
        self,
        registry_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """List items inside a registry."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            items = await service.list_items(UUID(registry_id), limit=limit, offset=offset)
            return json.dumps([_item_summary(i) for i in items], default=str)

    @tool_method
    async def search_catalog(
        self,
        query: str = "",
        tag: str = "",
        update_available: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> str:
        """Search across all registry catalogs in the workspace."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            items = await service.search_catalog(
                query=query or None,
                tag=tag or None,
                update_available=update_available or None,
                limit=limit,
                offset=offset,
            )
            return json.dumps([_item_summary(i) for i in items], default=str)

    @tool_method
    async def get_item(self, item_id: str) -> str:
        """Get details of a catalog item."""
        async with platform_read_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            item = await service.get_item(UUID(item_id))
            if not item:
                return json.dumps({"error": "Catalog item not found"})
            data = _item_summary(item)
            data["spec"] = item.spec or {}
            return json.dumps(data, default=str)

    @tool_method
    async def sync_registry(self, registry_id: str) -> str:
        """Re-sync a registry from its source."""
        async with platform_context() as (session, user_ctx, _repo, _broker, _secret):
            service = _build_registry_service(session, user_ctx)
            stats = await service.sync_registry(UUID(registry_id))
            return json.dumps(stats, default=str)
