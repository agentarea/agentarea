"""A changed LLM catalog item reaches its entity; other types only flag an update.

A provider's or model's catalog row is the platform's own: when the source changes
it (a new base_url, a vision flag), the spec it installed must change too. Before,
a change with the same version left the entity as it was, so catalog edits never
landed.
"""

from uuid import NAMESPACE_URL, uuid5

import pytest_asyncio
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)


@pytest_asyncio.fixture
async def catalog(db_session, monkeypatch):
    service = RegistryService(
        RegistryRepository(db_session), RegistryItemRepository(db_session), server_repo=None
    )
    applied: list[str] = []
    source = {"items": []}

    async def create_entity(self, registry_type, item, registry_url=None):
        return uuid5(NAMESPACE_URL, item.external_id)

    async def update_entity(self, registry_type, item, registry_url=None):
        applied.append(item.external_id)

    monkeypatch.setattr(RegistryService, "_create_entity", create_entity)
    monkeypatch.setattr(RegistryService, "_update_entity", update_entity)
    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(lambda _url: {}))
    monkeypatch.setattr(
        RegistryService,
        "_parse_source",
        staticmethod(lambda _type, _data: [dict(item) for item in source["items"]]),
    )

    async def make(registry_type: str) -> Registry:
        registry = Registry(
            name=registry_type,
            registry_type=registry_type,
            source_type="url",
            source_url=f"https://example.test/{registry_type}.json",
        )
        db_session.add(registry)
        await db_session.commit()
        return registry

    return service, make, source, applied


def _item(spec: dict, version: str = "1.0.0") -> dict:
    return {"external_id": "gemini", "name": "Gemini", "version": version, "spec": spec}


async def test_a_changed_provider_item_is_applied_to_its_spec(catalog):
    service, make, source, applied = catalog
    registry = await make("llm_providers")
    source["items"] = [_item({"provider_key": "gemini"})]
    await service.sync_registry(registry.id, force=True)

    source["items"] = [_item({"provider_key": "gemini", "base_url": "https://g.example/v1"})]
    stats = await service.sync_registry(registry.id, force=True)

    assert applied == ["gemini"]
    assert (stats["applied"], stats["unchanged"], stats["updates_flagged"]) == (1, 0, 0)


async def test_an_unchanged_provider_item_is_not_applied_again(catalog):
    service, make, source, applied = catalog
    registry = await make("llm_providers")
    source["items"] = [_item({"provider_key": "gemini"})]
    await service.sync_registry(registry.id, force=True)

    stats = await service.sync_registry(registry.id, force=True)

    assert applied == []
    assert (stats["unchanged"], stats["skipped"]) == (1, 0)


async def test_a_changed_mcp_item_with_the_same_version_is_not_applied(catalog):
    service, make, source, applied = catalog
    registry = await make("mcp_servers")
    source["items"] = [_item({"name": "x", "description": "old"})]
    await service.sync_registry(registry.id, force=True)

    source["items"] = [_item({"name": "x", "description": "new"})]
    stats = await service.sync_registry(registry.id, force=True)

    assert applied == []
    assert (stats["applied"], stats["unchanged"], stats["skipped"]) == (0, 1, 0)
