"""Contract and trust-boundary tests for one-click connection OAuth."""

import json
import urllib.parse
from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import connection_oauth
from agentarea_api.api.v1.oauth_app_credentials import workspace_secret_value
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_secrets.catalog_service import SecretCatalogService
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
        get_for_use=AsyncMock(side_effect=[client_id_secret, client_secret_secret]),
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


def _catalog_holding(secret, user_id: str, admin_workspaces: list[str]) -> SecretCatalogService:
    """The catalog's own selection rule, over a session that finds ``secret``."""
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: secret)
    user = UserContext(user_id=user_id, workspace_id="ws", admin_workspaces=admin_workspaces)
    return SecretCatalogService(session, user, AsyncMock())


def _user_secret(created_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        secret_name="member_a_client_id",  # noqa: S106  # pragma: allowlist secret
        owner_type=None,
        owner_id=None,
        created_by=created_by,
    )


@pytest.mark.asyncio
async def test_workspace_secret_source_rejects_connection_owned_secret():
    secret = SimpleNamespace(
        id=uuid4(),
        secret_name="mcp_auth_cred:managed",  # noqa: S106  # pragma: allowlist secret
        owner_type="mcp_auth_config",
        owner_id=str(uuid4()),
        created_by="admin",
    )
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="must-not-be-read"))

    with pytest.raises(HTTPException, match="must be a user-owned workspace secret"):
        await workspace_secret_value(
            _catalog_holding(secret, "admin", ["ws"]),
            manager,
            secret.id,
            "client secret",
        )

    manager.get_secret.assert_not_awaited()


@pytest.mark.asyncio
async def test_workspace_secret_source_refuses_another_members_secret():
    # The client ID comes back inside the authorize URL, so selecting a
    # secret someone else created would read its plaintext.
    secret = _user_secret(created_by="member-a")
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="member-a-value"))

    with pytest.raises(HTTPException) as exc_info:
        await workspace_secret_value(
            _catalog_holding(secret, "member-b", []), manager, secret.id, "client ID"
        )

    assert exc_info.value.status_code == 403
    manager.get_secret.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("user_id", "admin_workspaces"), [("member-a", []), ("workspace-admin", ["ws"])]
)
async def test_workspace_secret_source_allows_the_creator_or_an_admin(user_id, admin_workspaces):
    secret = _user_secret(created_by="member-a")
    manager = SimpleNamespace(get_secret=AsyncMock(return_value="member-a-value"))

    resolved, value = await workspace_secret_value(
        _catalog_holding(secret, user_id, admin_workspaces), manager, secret.id, "client ID"
    )

    assert resolved is secret
    assert value == "member-a-value"
