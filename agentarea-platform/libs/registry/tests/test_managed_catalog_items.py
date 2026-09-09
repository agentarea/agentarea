"""Platform-managed catalog definitions are data, not image-bundled code."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_registry.application.service import (
    CatalogItemAlreadyExistsError,
    RegistryService,
)


def _service(*, source_type: str = "managed", registry_type: str = "mcp_servers"):
    registry_id = uuid4()
    registry = SimpleNamespace(
        id=registry_id,
        source_type=source_type,
        registry_type=registry_type,
    )
    registry_repo = SimpleNamespace(
        get_by_id=AsyncMock(return_value=registry),
        update=AsyncMock(),
        create=AsyncMock(),
    )
    item_repo = SimpleNamespace(
        get_by_id=AsyncMock(),
        get_by_external_id=AsyncMock(return_value=None),
        create=AsyncMock(),
        update=AsyncMock(),
        delete=AsyncMock(return_value=True),
        count_by_registry=AsyncMock(return_value=1),
    )
    return RegistryService(registry_repo, item_repo, server_repo=None), registry, item_repo


async def test_managed_registry_does_not_need_a_fetch_url():
    service, _, _ = _service()

    await service.create_registry(
        name="private-connectors",
        registry_type="mcp_servers",
        source_type="managed",
        source_url=None,
    )

    assert service.registry_repo.create.await_args.kwargs["source_url"] == "managed://catalog"


async def test_create_managed_openapi_item_derives_gallery_facets_and_updates_count():
    service, registry, item_repo = _service()
    created = SimpleNamespace(id=uuid4())
    item_repo.create.return_value = created

    result = await service.create_catalog_item(
        registry.id,
        external_id="ai.agentarea.catalog/yandex-metrica",
        name="Yandex Metrica",
        version="1.0.0",
        spec={
            "connection_type": "openapi",
            "raw_spec": {"metadata": {"agentarea:category": "analytics"}},
        },
        tags=["featured"],
    )

    assert result is created
    written = item_repo.create.await_args.kwargs
    assert written["category"] == "analytics"
    assert written["sort_key"] == "yandex metrica"
    assert written["featured"] is True
    service.registry_repo.update.assert_awaited_once_with(registry.id, item_count=1)


async def test_direct_write_rejects_a_synchronized_registry():
    service, registry, _ = _service(source_type="url")

    with pytest.raises(ValueError, match="managed registry"):
        await service.create_catalog_item(
            registry.id,
            external_id="connector",
            name="Connector",
        )


async def test_duplicate_external_id_is_rejected_with_a_domain_conflict():
    service, registry, item_repo = _service()
    item_repo.get_by_external_id.return_value = SimpleNamespace(id=uuid4())

    with pytest.raises(CatalogItemAlreadyExistsError):
        await service.create_catalog_item(
            registry.id,
            external_id="connector",
            name="Connector",
        )


async def test_update_recomputes_facets_from_the_new_definition():
    service, registry, item_repo = _service()
    item = SimpleNamespace(
        id=uuid4(),
        registry_id=registry.id,
        external_id="connector",
        name="Old name",
        spec={},
        tags=[],
    )
    item_repo.get_by_id.return_value = item
    updated = SimpleNamespace(id=item.id)
    item_repo.update.return_value = updated

    result = await service.update_catalog_item(
        item.id,
        name="New name",
        tags=["featured"],
    )

    assert result is updated
    assert item_repo.update.await_args.kwargs == {
        "name": "New name",
        "tags": ["featured"],
        "category": None,
        "sort_key": "new name",
        "featured": True,
    }


async def test_delete_updates_the_registry_item_count():
    service, registry, item_repo = _service()
    item = SimpleNamespace(id=uuid4(), registry_id=registry.id)
    item_repo.get_by_id.return_value = item
    item_repo.count_by_registry.return_value = 4

    await service.delete_catalog_item(item.id)

    item_repo.delete.assert_awaited_once_with(item.id)
    service.registry_repo.update.assert_awaited_once_with(registry.id, item_count=4)
