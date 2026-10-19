"""A source that has not changed since the last sync is not read again.

Reconcile runs hourly and the sources change daily; every run re-read and
re-applied every catalog row regardless.
"""

import urllib.error
import urllib.request

import pytest_asyncio
from agentarea_registry.application.service import RegistryService
from agentarea_registry.domain.models import Registry
from agentarea_registry.infrastructure.repository import (
    RegistryItemRepository,
    RegistryRepository,
)

# Taken before conftest's autouse fixture replaces it for every test.
_REAL_SOURCE_ETAG = RegistryService._source_etag


@pytest_asyncio.fixture
async def source(db_session, monkeypatch):
    service = RegistryService(
        RegistryRepository(db_session), RegistryItemRepository(db_session), server_repo=None
    )
    registry = Registry(
        name="bundles",
        registry_type="bundles",
        source_type="url",
        source_url="https://example.test/bundles.json",
    )
    db_session.add(registry)
    await db_session.commit()

    state = {"etag": '"v1"', "reads": 0}

    def fetch(_url):
        state["reads"] += 1
        return {"bundles": [{"name": "alpha", "schema_version": "0.1.0"}]}

    monkeypatch.setattr(RegistryService, "_fetch_source", staticmethod(fetch))
    monkeypatch.setattr(RegistryService, "_source_etag", staticmethod(lambda _url: state["etag"]))
    return service, registry, state


async def test_an_unchanged_source_is_not_read_again(source):
    service, registry, state = source
    await service.sync_registry(registry.id)

    stats = await service.sync_registry(registry.id)

    assert stats["source_unchanged"] is True
    assert state["reads"] == 1


async def test_a_changed_source_is_read(source):
    service, registry, state = source
    await service.sync_registry(registry.id)

    state["etag"] = '"v2"'
    await service.sync_registry(registry.id)

    assert state["reads"] == 2


async def test_force_reads_an_unchanged_source(source):
    service, registry, state = source
    await service.sync_registry(registry.id)

    await service.sync_registry(registry.id, force=True)

    assert state["reads"] == 2


async def test_a_source_with_skipped_items_is_read_again(source, monkeypatch):
    service, registry, state = source
    original = RegistryService._parse_source

    def parse_with_a_bad_item(registry_type, data):
        items = original(registry_type, data)
        return [*items, {"external_id": "broken"}]  # no name: creating it raises

    monkeypatch.setattr(RegistryService, "_parse_source", staticmethod(parse_with_a_bad_item))
    first = await service.sync_registry(registry.id)
    assert first["skipped"] == 1

    await service.sync_registry(registry.id)

    assert state["reads"] == 2


def test_a_source_refusing_head_is_read_in_full(monkeypatch):
    # A presigned GET URL or an API without HEAD has no ETag to offer: no skip.
    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError("https://example.test/s.json", 403, "Forbidden", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", refuse)

    assert _REAL_SOURCE_ETAG("https://example.test/s.json") is None
