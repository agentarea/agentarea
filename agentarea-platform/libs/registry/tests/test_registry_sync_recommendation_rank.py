"""Sync persists the order the source published, and re-sync follows it.

Catalog sources are authored best-first — the curated skills artifact is
generated in GitHub-star order, the connection artifact leads with the official
integrations every workspace wants. Sync used to drop that position on the
floor, which left /explore alphabetical no matter how the catalog was curated.
"""

import pytest_asyncio
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)


def _catalog(*names: str) -> dict:
    # Bundles are catalog-only (nothing is materialized on sync), so this
    # exercises the ordering without dragging in entity repositories.
    return {"bundles": [{"name": n, "schema_version": "0.1.0"} for n in names]}


@pytest_asyncio.fixture
async def catalog(db_session, monkeypatch):
    item_repo = RegistryItemRepository(db_session)
    service = RegistryService(
        RegistryRepository(db_session), item_repo, server_repo=None
    )

    registry = Registry(
        name="bundles",
        registry_type="bundles",
        source_type="url",
        source_url="https://example.test/bundles.json",
    )
    db_session.add(registry)
    await db_session.commit()
    await db_session.refresh(registry)

    published = {"payload": _catalog("zulu", "alpha")}
    monkeypatch.setattr(
        RegistryService, "_fetch_source", staticmethod(lambda _url: published["payload"])
    )

    async def browse() -> list[str]:
        items, _ = await item_repo.browse("bundles", limit=10)
        return [i.name for i in items]

    return service, registry, published, browse


async def test_the_catalog_opens_in_the_order_the_source_published(catalog):
    service, registry, _, browse = catalog

    await service.sync_registry(registry.id)

    # Alphabetical would put "alpha" first; the curator put "zulu" first.
    assert await browse() == ["zulu", "alpha"]


async def test_resync_follows_a_reshuffled_source(catalog):
    service, registry, published, browse = catalog
    await service.sync_registry(registry.id)

    published["payload"] = _catalog("alpha", "zulu")
    await service.sync_registry(registry.id)

    # Keeping the first sync's rank would pin the catalog to whatever order it
    # happened to be published in on install day.
    assert await browse() == ["alpha", "zulu"]
