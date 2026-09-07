"""Contract and trust-boundary tests for one-click connection OAuth."""

import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import connection_oauth
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException


def _oauth_profile() -> dict:
    return {
        "provider_key": "yandex-metrica",
        "authorization_url": "https://oauth.yandex.ru/authorize",
        "token_url": "https://oauth.yandex.ru/token",
        "managed_credentials_key": "connection_oauth_client:yandex-metrica",
        "allowed_api_origins": ["https://api-metrika.yandex.net"],
        "scopes": ["metrika:read"],
        "authorization_scheme": "OAuth",
        "client_auth_method": "client_secret_post",
    }


def test_catalog_oauth_rejects_unreserved_platform_secret_reference(monkeypatch):
    monkeypatch.setattr(connection_oauth, "validate_url", lambda *_args, **_kwargs: None)
    profile = _oauth_profile()
    profile["managed_credentials_key"] = "unrelated-platform-key"

    with pytest.raises(HTTPException, match="Invalid managed OAuth secret key"):
        connection_oauth._oauth_profile({"oauth": profile})


@pytest.mark.asyncio
async def test_managed_connect_is_one_click_and_state_contains_no_secret(monkeypatch):
    item_id = uuid4()
    connection_id = uuid4()
    auth_config_id = uuid4()
    item = SimpleNamespace(
        registry_id=uuid4(),
        name="Yandex Metrica",
        description="Read-only analytics",
        spec={
            "connection_type": "openapi",
            "base_url": "https://api-metrika.yandex.net",
            "spec_content": {"openapi": "3.1.0", "paths": {}},
        },
    )
    registry = SimpleNamespace(registry_type="mcp_servers", is_active=True)

    class _ItemRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, requested_id):
            assert requested_id == item_id
            return item

    class _RegistryRepository:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_id(self, requested_id):
            assert requested_id == item.registry_id
            return registry

    connection_create = AsyncMock(return_value=SimpleNamespace(id=connection_id))

    class _ConnectionService:
        def __init__(self, *_args, **_kwargs):
            pass

        async def get_by_registry_item_id(self, requested_id):
            assert requested_id == item_id
            return None

        create_connection = connection_create

    auth_create = AsyncMock(return_value=SimpleNamespace(id=auth_config_id))

    class _AuthService:
        def __init__(self, *_args, **_kwargs):
            pass

        create = auth_create

    stored_state = AsyncMock()
    monkeypatch.setattr(connection_oauth, "RegistryItemRepository", _ItemRepository)
    monkeypatch.setattr(connection_oauth, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(connection_oauth, "OpenAPIConnectionService", _ConnectionService)
    monkeypatch.setattr(connection_oauth, "MCPAuthService", _AuthService)
    monkeypatch.setattr(connection_oauth, "RepositoryFactory", lambda *_args: object())
    monkeypatch.setattr(connection_oauth, "get_real_secret_manager", lambda **_kwargs: object())
    monkeypatch.setattr(connection_oauth, "_managed_secret_manager", lambda _session: object())
    monkeypatch.setattr(
        connection_oauth,
        "_managed_credentials",
        AsyncMock(return_value=("managed-client-id", "managed-client-secret")),
    )
    monkeypatch.setattr(connection_oauth, "_oauth_profile", lambda _spec: _oauth_profile())
    monkeypatch.setattr(connection_oauth, "_store_state", stored_state)
    monkeypatch.setattr(
        connection_oauth,
        "_callback_uri",
        lambda: "https://api.agentarea.ru/v1/connections/oauth/callback",
    )

    response = await connection_oauth.connect_catalog_item(
        item_id,
        connection_oauth.CatalogConnectionRequest(return_to="https://app.agentarea.ru"),
        UserContext(user_id=str(uuid4()), workspace_id=str(uuid4())),
        AsyncMock(),
    )

    assert response.connection_id == connection_id
    query = urllib.parse.parse_qs(urllib.parse.urlparse(response.authorize_url).query)
    assert query["client_id"] == ["managed-client-id"]
    assert query["redirect_uri"] == ["https://api.agentarea.ru/v1/connections/oauth/callback"]
    assert query["scope"] == ["metrika:read"]
    assert query["code_challenge_method"] == ["S256"]

    auth_kwargs = auth_create.await_args.kwargs
    assert auth_kwargs["allow_managed_credentials"] is True
    assert auth_kwargs["credentials"] == {}
    state_payload = stored_state.await_args.args[1]
    assert "client_secret" not in state_payload
    assert state_payload["connection_id"] == str(connection_id)
