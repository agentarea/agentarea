"""HTTP contract for publishing private catalog definitions through the API."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_api.api.v1 import registries
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_registry.application.service import CatalogItemAlreadyExistsError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _item(**overrides):
    values = {
        "id": uuid4(),
        "registry_id": uuid4(),
        "external_id": "ai.agentarea.catalog/yandex-metrica",
        "name": "Yandex Metrica",
        "description": None,
        "version": "1.0.0",
        "spec": {"connection_type": "openapi"},
        "tags": [],
        "installed_entity_id": None,
        "update_available": False,
        "installed_version": None,
        "category": "analytics",
        "featured": False,
        "created_at": datetime(2026, 9, 9),
        "updated_at": datetime(2026, 9, 9),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client_for(service) -> AsyncClient:
    app = FastAPI()
    app.include_router(registries.router, prefix="/v1")
    app.dependency_overrides[registries.get_registry_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="platform", workspace_id="platform"
    )
    app.dependency_overrides[registries.require_platform_catalog_write] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_post_creates_one_catalog_item():
    registry_id = uuid4()
    service = SimpleNamespace(create_catalog_item=AsyncMock(return_value=_item()))

    async with _client_for(service) as client:
        response = await client.post(
            f"/v1/registries/{registry_id}/items",
            json={
                "external_id": "ai.agentarea.catalog/yandex-metrica",
                "name": "Yandex Metrica",
                "spec": {"connection_type": "openapi"},
            },
        )

    assert response.status_code == 201
    assert response.json()["name"] == "Yandex Metrica"
    service.create_catalog_item.assert_awaited_once_with(
        registry_id,
        external_id="ai.agentarea.catalog/yandex-metrica",
        name="Yandex Metrica",
        description=None,
        version=None,
        spec={"connection_type": "openapi"},
        tags=[],
    )


async def test_post_maps_duplicate_to_conflict():
    registry_id = uuid4()
    service = SimpleNamespace(
        create_catalog_item=AsyncMock(side_effect=CatalogItemAlreadyExistsError("duplicate"))
    )

    async with _client_for(service) as client:
        response = await client.post(
            f"/v1/registries/{registry_id}/items",
            json={"external_id": "duplicate", "name": "Duplicate"},
        )

    assert response.status_code == 409


async def test_patch_updates_an_item():
    item = _item(name="Renamed")
    service = SimpleNamespace(update_catalog_item=AsyncMock(return_value=item))

    async with _client_for(service) as client:
        response = await client.patch(
            f"/v1/registries/catalog/items/{item.id}",
            json={"name": "Renamed"},
        )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    service.update_catalog_item.assert_awaited_once_with(item.id, name="Renamed")


async def test_delete_removes_an_item():
    item_id = uuid4()
    service = SimpleNamespace(delete_catalog_item=AsyncMock(return_value=None))

    async with _client_for(service) as client:
        response = await client.delete(f"/v1/registries/catalog/items/{item_id}")

    assert response.status_code == 204
    service.delete_catalog_item.assert_awaited_once_with(item_id)
