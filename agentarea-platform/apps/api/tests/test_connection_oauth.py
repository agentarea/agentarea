"""Contract and trust-boundary tests for one-click connection OAuth."""

import json
import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
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

    with pytest.raises(HTTPException, match="Invalid managed OAuth credential reference"):
        connection_oauth._oauth_profile({"oauth": profile})


@pytest.mark.asyncio
@pytest.mark.parametrize("credential_source", ["managed", "inline", "workspace_secrets"])
async def test_connect_uses_requested_credential_source_without_secret_in_state(
    monkeypatch, credential_source
):
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
    client_id_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="metrika_client_id",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    client_secret_secret = SimpleNamespace(
        id=uuid4(),
        secret_name="metrika_client_secret",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
    )
    workspace_manager = SimpleNamespace(
        get_secret=AsyncMock(
            side_effect=lambda name: {
                "metrika_client_id": "workspace-client-id",
                "metrika_client_secret": "workspace-client-secret",  # pragma: allowlist secret
            }.get(name)
        )
    )
    secret_catalog = SimpleNamespace(
        get=AsyncMock(side_effect=[client_id_secret, client_secret_secret]),
        add_reference=AsyncMock(),
    )
    monkeypatch.setattr(
        connection_oauth, "get_real_secret_manager", lambda **_kwargs: workspace_manager
    )
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

    if credential_source == "managed":
        body = connection_oauth.CatalogConnectionRequest(return_to="https://app.agentarea.ru")
    elif credential_source == "inline":
        body = connection_oauth.CatalogConnectionRequest(
            credential_mode="custom",
            client_id="inline-client-id",
            client_secret="inline-client-secret",  # noqa: S106  # pragma: allowlist secret
            return_to="https://app.agentarea.ru",
        )
    else:
        body = connection_oauth.CatalogConnectionRequest(
            credential_mode="custom",
            client_id_secret_id=client_id_secret.id,
            client_secret_secret_id=client_secret_secret.id,
            return_to="https://app.agentarea.ru",
        )

    response = await connection_oauth.connect_catalog_item(
        item_id,
        body,
        UserContext(user_id=str(uuid4()), workspace_id=str(uuid4())),
        AsyncMock(),
        secret_catalog,
    )

    assert response.connection_id == connection_id
    connection_create.assert_awaited_once()
    assert connection_create.await_args.kwargs["registry_item_id"] == item_id
    query = urllib.parse.parse_qs(urllib.parse.urlparse(response.authorize_url).query)
    expected_client_id = {
        "managed": "managed-client-id",
        "inline": "inline-client-id",
        "workspace_secrets": "workspace-client-id",  # pragma: allowlist secret
    }[credential_source]
    assert query["client_id"] == [expected_client_id]
    assert query["redirect_uri"] == ["https://api.agentarea.ru/v1/connections/oauth/callback"]
    assert query["scope"] == ["metrika:read"]
    assert query["code_challenge_method"] == ["S256"]

    auth_kwargs = auth_create.await_args.kwargs
    assert auth_kwargs["allow_managed_credentials"] is True
    if credential_source == "managed":
        assert auth_kwargs["credentials"] == {}
        assert auth_kwargs["config"]["client_id"] == "managed-client-id"
        secret_catalog.add_reference.assert_not_awaited()
    elif credential_source == "inline":
        assert auth_kwargs["config"]["client_id"] == "inline-client-id"
        assert auth_kwargs["credentials"] == {  # pragma: allowlist secret
            "client_secret": "inline-client-secret"  # pragma: allowlist secret
        }
        secret_catalog.add_reference.assert_not_awaited()
    else:
        assert auth_kwargs["credentials"] == {}
        assert "client_id" not in auth_kwargs["config"]
        assert (
            auth_kwargs["config"]["client_id_secret_name"] == "metrika_client_id"  # noqa: S105
        )
        assert (
            auth_kwargs["config"]["client_secret_secret_name"] == "metrika_client_secret"  # noqa: S105  # pragma: allowlist secret
        )
        assert secret_catalog.add_reference.await_args_list == [
            call(client_id_secret.id, "mcp_auth_config", str(auth_config_id), "client_id"),
            call(
                client_secret_secret.id,
                "mcp_auth_config",
                str(auth_config_id),
                "client_secret",
            ),
        ]
    state_payload = stored_state.await_args.args[1]
    assert "client_secret" not in state_payload
    assert state_payload["connection_id"] == str(connection_id)


@pytest.mark.asyncio
async def test_oauth_state_is_consumed_atomically(monkeypatch):
    payload = {"connection_id": str(uuid4())}
    redis = SimpleNamespace(getdel=AsyncMock(return_value=json.dumps(payload)))
    monkeypatch.setattr(connection_oauth, "_redis", AsyncMock(return_value=redis))

    assert await connection_oauth._pop_state("one-time-state") == payload
    redis.getdel.assert_awaited_once_with("connection_oauth_state:one-time-state")


def test_custom_connect_requires_exactly_one_source_per_credential():
    secret_id = uuid4()

    with pytest.raises(ValueError, match="client ID must be entered or selected"):
        connection_oauth.CatalogConnectionRequest(
            credential_mode="custom",
            client_secret="secret",  # noqa: S106  # pragma: allowlist secret
        )

    with pytest.raises(ValueError, match="client secret must be entered or selected"):
        connection_oauth.CatalogConnectionRequest(
            credential_mode="custom",
            client_id="id",
            client_secret="secret",  # noqa: S106  # pragma: allowlist secret
            client_secret_secret_id=secret_id,
        )


@pytest.mark.asyncio
async def test_workspace_secret_source_rejects_connection_owned_secret():
    secret_id = uuid4()
    catalog = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                id=secret_id,
                secret_name="mcp_auth_cred:managed",  # noqa: S106  # pragma: allowlist secret
                owner_type="mcp_auth_config",
            )
        )
    )
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="must-not-be-read"))

    with pytest.raises(HTTPException, match="must be a user-owned workspace secret"):
        await connection_oauth._workspace_secret_value(
            catalog,
            manager,
            secret_id,
            "client secret",
        )

    manager.get_secret.assert_not_awaited()
