"""Connecting a catalog API with its keys instead of a sign-in."""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api import catalog_api
from agentarea_api.api.v1 import openapi_connections as routes
from agentarea_api.api.v1.openapi_connections import CatalogConnectRequest, CatalogKeyValue
from agentarea_common.auth.context import UserContext
from agentarea_openapi.application import url_validator
from fastapi import HTTPException

_FIELDS = [
    {"name": "Authorization", "location": "header", "scheme": "Token", "label": "API key"},
    {"name": "X-Secret", "location": "header", "label": "Secret key"},
    {"name": "key", "location": "query", "label": "Account key"},
]


def _item(**spec_over) -> SimpleNamespace:
    return SimpleNamespace(
        registry_id=uuid4(),
        name="Example Data",
        description="Company records",
        spec={
            "connection_type": "openapi",
            "base_url": "https://api.example.com",
            "spec_url": "https://catalog.example.com/openapi/example-data.json",
            "api_key": {"fields": _FIELDS, "allowed_api_origins": ["https://api.example.com"]},
            **spec_over,
        },
    )


def _patch_catalog(monkeypatch, item, registry=None):
    registry = registry or SimpleNamespace(registry_type="mcp_servers", is_active=True)

    class _ItemRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _requested_id):
            return item

    class _RegistryRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, _requested_id):
            return registry

    monkeypatch.setattr(catalog_api, "RegistryItemRepository", _ItemRepository)
    monkeypatch.setattr(catalog_api, "RegistryRepository", _RegistryRepository)


def _user() -> UserContext:
    return UserContext(user_id="user-1", workspace_id="ws-1")


def _service():
    return SimpleNamespace(create_connection=AsyncMock(return_value="created"))


def _request(**values) -> CatalogConnectRequest:
    return CatalogConnectRequest(
        credentials=[CatalogKeyValue(name=name, value=value) for name, value in values.items()]
    )


@pytest.fixture(autouse=True)
def _raw_response(monkeypatch):
    monkeypatch.setattr(routes, "_connection_response", lambda conn: conn)
    # The payload's URL check resolves the host; these hosts are fictional.
    monkeypatch.setattr(url_validator, "validate_url", lambda *_args, **_kwargs: None)


@pytest.mark.asyncio
async def test_the_form_lists_the_keys_a_catalog_api_needs(monkeypatch):
    _patch_catalog(monkeypatch, _item())
    item_id = uuid4()

    form = await routes.get_catalog_connect_form(item_id, _user(), object())

    assert form.auth == "api_key"
    assert form.catalog_item_id == item_id
    assert [(f.name, f.location, f.label) for f in form.fields] == [
        ("Authorization", "header", "API key"),
        ("X-Secret", "header", "Secret key"),
        ("key", "query", "Account key"),
    ]


@pytest.mark.asyncio
async def test_a_catalog_api_without_keys_is_connected_by_signing_in(monkeypatch):
    item = _item()
    del item.spec["api_key"]
    item.spec["oauth"] = {"provider_key": "example"}
    _patch_catalog(monkeypatch, item)

    form = await routes.get_catalog_connect_form(uuid4(), _user(), object())

    assert form.auth == "oauth"
    assert form.fields == []


@pytest.mark.asyncio
async def test_a_malformed_key_template_is_the_catalogs_fault(monkeypatch):
    _patch_catalog(monkeypatch, _item(api_key={"fields": [{"name": "k", "location": "cookie"}]}))

    with pytest.raises(HTTPException) as caught:
        await routes.get_catalog_connect_form(uuid4(), _user(), object())

    assert caught.value.status_code == 500


@pytest.mark.asyncio
async def test_connecting_stores_every_key_as_a_secret_of_a_new_connection(monkeypatch):
    _patch_catalog(monkeypatch, _item())
    service = _service()
    item_id = uuid4()

    result = await routes.connect_catalog_api(
        item_id,
        _request(Authorization="tok", **{"X-Secret": "sec"}, key="acct"),  # pragma: allowlist secret
        _user(),
        object(),
        service,
    )

    assert result == "created"
    payload = service.create_connection.await_args.args[0]
    assert payload.name == "Example Data"
    assert payload.base_url == "https://api.example.com"
    assert payload.spec_url == "https://catalog.example.com/openapi/example-data.json"
    assert [(h.name, h.value) for h in payload.custom_headers] == [
        ("Authorization", "Token tok"),
        ("X-Secret", "sec"),
    ]
    assert [(p.name, p.value, p.secret) for p in payload.custom_query_params] == [
        ("key", "acct", True)
    ]
    assert service.create_connection.await_args.kwargs == {"registry_item_id": item_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("values", "detail"),
    [
        ({"Authorization": "tok", "key": "acct"}, "Secret key is required"),
        ({"Authorization": "tok", "X-Secret": "sec", "key": "acct", "X-Other": "x"}, "X-Other"),  # pragma: allowlist secret
    ],
    ids=["missing", "unknown"],
)
async def test_the_keys_must_match_the_form(monkeypatch, values, detail):
    _patch_catalog(monkeypatch, _item())
    service = _service()

    with pytest.raises(HTTPException) as caught:
        await routes.connect_catalog_api(uuid4(), _request(**values), _user(), object(), service)

    assert caught.value.status_code == 400
    assert detail in caught.value.detail
    service.create_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_key_given_twice_is_refused(monkeypatch):
    _patch_catalog(monkeypatch, _item())
    request = CatalogConnectRequest(
        credentials=[
            CatalogKeyValue(name="key", value="a"),
            CatalogKeyValue(name="key", value="b"),
        ]
    )

    with pytest.raises(HTTPException) as caught:
        await routes.connect_catalog_api(uuid4(), request, _user(), object(), _service())

    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_an_oauth_catalog_api_cannot_be_connected_with_keys(monkeypatch):
    item = _item()
    del item.spec["api_key"]
    _patch_catalog(monkeypatch, item)

    with pytest.raises(HTTPException) as caught:
        await routes.connect_catalog_api(uuid4(), _request(key="x"), _user(), object(), _service())

    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_an_item_of_an_inactive_registry_is_not_connectable(monkeypatch):
    _patch_catalog(
        monkeypatch, _item(), SimpleNamespace(registry_type="mcp_servers", is_active=False)
    )

    with pytest.raises(HTTPException) as caught:
        await routes.get_catalog_connect_form(uuid4(), _user(), object())

    assert caught.value.status_code == 400
