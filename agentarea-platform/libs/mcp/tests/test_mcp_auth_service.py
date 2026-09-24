"""Unit tests for MCPAuthService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_mcp.application.auth_resolver import (
    build_auth_config_access_checker,
    build_auth_header_resolver,
)
from agentarea_mcp.application.auth_service import (
    AuthConfigAccessDeniedError,
    MCPAuthService,
    MissingCredentialsError,
    OAuthReauthRequiredError,
)
from agentarea_mcp.domain.auth_models import (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2,
    MCPAuthConfig,
)


class _FakeResp:
    def __init__(self, status_code: int = 200, data: dict | None = None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "err", request=MagicMock(), response=MagicMock(status_code=self.status_code)
            )


class _FakeClient:
    def __init__(self, resp: _FakeResp):
        self._resp = resp
        self.posted: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, data=None, timeout=None):
        self.posted = data
        return self._resp


def _oauth_config(**cfg) -> MCPAuthConfig:
    c = _make_config(AUTH_TYPE_OAUTH2, secret_key="k")  # noqa: S106
    c.config = {"token_url": "https://as/token", "client_id": "cid", **cfg}
    return c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(auth_type: str = AUTH_TYPE_API_KEY, **kwargs) -> MCPAuthConfig:
    cfg = MagicMock(spec=MCPAuthConfig)
    cfg.id = uuid4()
    cfg.auth_type = auth_type
    cfg.config = kwargs.get("config", {})
    cfg.secret_key = kwargs.get("secret_key", None)
    return cfg


def _make_service(repo=None, secret_manager=None):
    repo = repo or AsyncMock()
    secret_manager = secret_manager or AsyncMock()
    return MCPAuthService(repo, secret_manager), repo, secret_manager


# ---------------------------------------------------------------------------
# validate_credentials
# ---------------------------------------------------------------------------


class TestValidateCredentials:
    def test_api_key_requires_header_value(self):
        with pytest.raises(ValueError, match="header_value"):
            MCPAuthService.validate_credentials(AUTH_TYPE_API_KEY, {})

    def test_api_key_passes_with_header_value(self):
        MCPAuthService.validate_credentials(AUTH_TYPE_API_KEY, {"header_value": "secret"})

    def test_bearer_requires_token(self):
        with pytest.raises(ValueError, match="token"):
            MCPAuthService.validate_credentials(AUTH_TYPE_BEARER, {})

    def test_bearer_passes_with_token(self):
        MCPAuthService.validate_credentials(AUTH_TYPE_BEARER, {"token": "tok123"})

    def test_oauth2_requires_client_secret_or_access_token(self):
        with pytest.raises(ValueError, match="client_secret"):
            MCPAuthService.validate_credentials(AUTH_TYPE_OAUTH2, {})

    def test_oauth2_passes_with_client_secret(self):
        MCPAuthService.validate_credentials(AUTH_TYPE_OAUTH2, {"client_secret": "s3cr3t"})

    def test_oauth2_passes_with_access_token(self):
        MCPAuthService.validate_credentials(AUTH_TYPE_OAUTH2, {"access_token": "tok"})


# ---------------------------------------------------------------------------
# get_auth_headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetAuthHeaders:
    async def test_managed_auth_cannot_be_attached_to_an_untrusted_connection(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = _oauth_config(
            credential_mode="managed",
            managed_credentials_key="connection_oauth_client:yandex-metrica",
        )
        repo_factory = MagicMock()
        repo_factory.create_repository.return_value = repo
        workspace_sm = AsyncMock()
        managed_sm = AsyncMock()
        resolver = build_auth_header_resolver(repo_factory, workspace_sm, managed_sm)

        with pytest.raises(ValueError, match="trusted catalog connection"):
            await resolver(
                repo.get_by_id.return_value.id,
                "https://attacker.example",
                None,
            )

        workspace_sm.get_secret.assert_not_awaited()
        managed_sm.get_secret.assert_not_awaited()

    async def test_api_key_injects_custom_header(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"header_value": "MY_SECRET"})

        config = _make_config(
            AUTH_TYPE_API_KEY,
            config={"header_name": "X-My-Key"},
            secret_key="some_key",  # noqa: S106
        )
        headers = await svc.get_auth_headers(config)
        assert headers == {"X-My-Key": "MY_SECRET"}

    async def test_api_key_uses_default_header_name(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"header_value": "VAL"})

        config = _make_config(AUTH_TYPE_API_KEY, config={}, secret_key="k")  # noqa: S106
        headers = await svc.get_auth_headers(config)
        assert "X-API-Key" in headers

    async def test_bearer_injects_authorization_header(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"token": "abc123"})

        config = _make_config(AUTH_TYPE_BEARER, secret_key="k")  # noqa: S106
        headers = await svc.get_auth_headers(config)
        assert headers == {"Authorization": "Bearer abc123"}

    async def test_oauth_supports_provider_scheme_and_non_expiring_token(self):
        svc, _, sm = _make_service()
        config = _oauth_config(authorization_scheme="OAuth")
        sm.get_secret.return_value = json.dumps({"access_token": "ya-token"})

        headers = await svc.get_auth_headers(config)

        assert headers == {"Authorization": "OAuth ya-token"}

    async def test_missing_secret_is_reported_not_sent_empty(self):
        """A vanished secret must not become an empty header.

        It used to: get_auth_headers returned `{"X-Key": ""}` and the request
        went out, so the user saw a 401 from the upstream server and went
        looking there instead of at the credential that was gone.
        """
        svc, _, sm = _make_service()
        sm.get_secret.return_value = None

        config = _make_config(AUTH_TYPE_API_KEY, config={"header_name": "X-Key"})
        with pytest.raises(MissingCredentialsError):
            await svc.get_auth_headers(config)

    async def test_empty_stored_api_key_is_reported(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"header_value": ""})

        config = _make_config(AUTH_TYPE_API_KEY, config={"header_name": "X-Key"})
        with pytest.raises(MissingCredentialsError):
            await svc.get_auth_headers(config)


# ---------------------------------------------------------------------------
# OAuth2 token refresh / reauth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOAuth2Refresh:
    async def test_valid_token_is_returned_without_refresh(self):
        svc, _, sm = _make_service()
        import time

        sm.get_secret.return_value = json.dumps(
            {"access_token": "still-good", "expires_at": time.time() + 3600}
        )
        headers = await svc.get_auth_headers(_oauth_config())
        assert headers == {"Authorization": "Bearer still-good"}

    async def test_expired_token_refreshes_via_refresh_token(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps(
            {"access_token": "old", "expires_at": 0, "refresh_token": "rt"}
        )
        client = _FakeClient(_FakeResp(200, {"access_token": "new", "expires_in": 3600}))
        with patch("httpx.AsyncClient", lambda *a, **k: client):
            headers = await svc.get_auth_headers(_oauth_config())
        assert headers == {"Authorization": "Bearer new"}
        assert client.posted["grant_type"] == "refresh_token"
        # Public client: no secret was sent.
        assert "client_secret" not in client.posted
        sm.set_secret.assert_called()  # persisted the rotated creds

    async def test_managed_refresh_reads_platform_secret(self):
        repo = AsyncMock()
        workspace_sm = AsyncMock()
        managed_sm = AsyncMock()
        svc = MCPAuthService(repo, workspace_sm, managed_sm)
        managed_key = "connection_oauth_client:yandex-metrica"
        expected_credential = "credential-value"
        config = _oauth_config(
            credential_mode="managed",
            managed_credentials_key=managed_key,
        )
        workspace_sm.get_secret.return_value = json.dumps(
            {"refresh_token": "refresh", "expires_at": 0}
        )
        managed_sm.get_secret.return_value = json.dumps(
            {"client_id": "managed-id", "client_secret": expected_credential}
        )
        client = _FakeClient(_FakeResp(200, {"access_token": "fresh", "expires_in": 3600}))

        with patch("httpx.AsyncClient", lambda *a, **k: client):
            headers = await svc.get_auth_headers(config)

        assert headers == {"Authorization": "Bearer fresh"}
        assert client.posted["client_id"] == "managed-id"
        assert client.posted["client_secret"] == expected_credential
        managed_sm.get_secret.assert_awaited_once_with(managed_key)

    async def test_custom_refresh_resolves_workspace_secret_references(self):
        svc, _, workspace_sm = _make_service()
        config = _oauth_config(
            client_id=None,
            client_id_secret_name="metrika_client_id",  # noqa: S106
            client_secret_secret_name="metrika_client_secret",  # noqa: S106  # pragma: allowlist secret
        )
        workspace_sm.get_secret.side_effect = lambda key: {
            "k": json.dumps({"refresh_token": "refresh", "expires_at": 0}),
            "metrika_client_id": "workspace-client-id",
            "metrika_client_secret": "workspace-client-secret",  # pragma: allowlist secret
        }.get(key)
        client = _FakeClient(_FakeResp(200, {"access_token": "fresh", "expires_in": 3600}))

        with patch("httpx.AsyncClient", lambda *a, **k: client):
            headers = await svc.get_auth_headers(config)

        assert headers == {"Authorization": "Bearer fresh"}
        assert client.posted["client_id"] == "workspace-client-id"
        assert (
            client.posted["client_secret"] == "workspace-client-secret"  # noqa: S105  # pragma: allowlist secret
        )

    async def test_force_refresh_refreshes_even_when_unexpired(self):
        svc, _, sm = _make_service()
        import time

        sm.get_secret.return_value = json.dumps(
            {"access_token": "good", "expires_at": time.time() + 3600, "refresh_token": "rt"}
        )
        client = _FakeClient(_FakeResp(200, {"access_token": "forced", "expires_in": 3600}))
        with patch("httpx.AsyncClient", lambda *a, **k: client):
            headers = await svc.get_auth_headers(_oauth_config(), force_refresh=True)
        assert headers == {"Authorization": "Bearer forced"}

    async def test_no_refresh_token_and_no_secret_requires_reauth(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"access_token": "dead", "expires_at": 0})
        with pytest.raises(OAuthReauthRequiredError):
            await svc.get_auth_headers(_oauth_config())

    async def test_refresh_4xx_requires_reauth(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps(
            {"access_token": "old", "expires_at": 0, "refresh_token": "revoked"}
        )
        client = _FakeClient(_FakeResp(400, {"error": "invalid_grant"}))
        with patch("httpx.AsyncClient", lambda *a, **k: client):
            with pytest.raises(OAuthReauthRequiredError):
                await svc.get_auth_headers(_oauth_config())


# ---------------------------------------------------------------------------
# create / delete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateDelete:
    async def test_managed_create_requires_a_reserved_credentials_reference(self):
        svc, repo, _ = _make_service()

        with pytest.raises(ValueError, match="Invalid managed OAuth credential reference"):
            await svc.create(
                name="Incomplete managed config",
                auth_type=AUTH_TYPE_OAUTH2,
                config={
                    "token_url": "https://provider.example/token",
                    "client_id": "ignored",
                    "credential_mode": "managed",
                },
                credentials={},
                allow_managed_credentials=True,
            )

        repo.create.assert_not_awaited()

    async def test_public_create_cannot_claim_managed_platform_credentials(self):
        svc, repo, _ = _make_service()
        placeholder_credential = "decoy"

        with pytest.raises(ValueError, match="only be created by a catalog connection"):
            await svc.create(
                name="Forged managed config",
                auth_type=AUTH_TYPE_OAUTH2,
                config={
                    "token_url": "https://attacker.example/token",
                    "client_id": "ignored",
                    "credential_mode": "managed",
                    "managed_credentials_key": "connection_oauth_client:yandex-metrica",
                },
                credentials={"client_secret": placeholder_credential},
            )

        repo.create.assert_not_awaited()

    async def test_public_create_cannot_reference_workspace_secrets(self):
        svc, repo, _ = _make_service()

        with pytest.raises(ValueError, match="only be created by a catalog connection"):
            await svc.create(
                name="Forged workspace reference",
                auth_type=AUTH_TYPE_OAUTH2,
                config={
                    "token_url": "https://attacker.example/token",
                    "client_id": "attacker-id",
                    "client_secret_secret_name": "valuable_workspace_secret",  # pragma: allowlist secret
                },
                credentials={},
            )

        repo.create.assert_not_awaited()

    async def test_public_update_cannot_redirect_managed_token_exchange(self):
        svc, repo, sm = _make_service()
        config_id = uuid4()
        managed = _oauth_config(
            credential_mode="managed",
            managed_credentials_key="connection_oauth_client:yandex-metrica",
        )
        repo.get.return_value = managed

        with pytest.raises(ValueError, match="only be changed by reconnecting"):
            await svc.update(
                config_id,
                config={
                    **managed.config,
                    "token_url": "https://attacker.example/token",
                },
            )

        repo.update.assert_not_awaited()
        sm.set_secret.assert_not_awaited()

    async def test_public_update_cannot_redirect_workspace_secret_exchange(self):
        svc, repo, sm = _make_service()
        config_id = uuid4()
        referenced = _oauth_config(
            client_id=None,
            client_id_secret_name="metrika_client_id",  # noqa: S106
            client_secret_secret_name="metrika_client_secret",  # noqa: S106  # pragma: allowlist secret
        )
        repo.get.return_value = referenced

        with pytest.raises(ValueError, match="only be changed by reconnecting"):
            await svc.update(
                config_id,
                config={
                    **referenced.config,
                    "token_url": "https://attacker.example/token",
                },
            )

        repo.update.assert_not_awaited()
        sm.set_secret.assert_not_awaited()

    async def test_create_stores_credentials(self):
        svc, repo, sm = _make_service()

        created_cfg = _make_config(AUTH_TYPE_API_KEY)
        repo.create.return_value = created_cfg
        repo.update.return_value = created_cfg

        result = await svc.create(
            name="Test",
            auth_type=AUTH_TYPE_API_KEY,
            config={"header_name": "X-Key"},
            credentials={"header_value": "secret"},
        )

        sm.set_secret.assert_called_once()
        repo.update.assert_called_once()
        assert result is created_cfg

    async def test_delete_raises_if_linked_instances(self):
        svc, repo, _ = _make_service()
        config_id = uuid4()
        repo.get_linked_instance_ids.return_value = ["inst-1", "inst-2"]
        repo.get_linked_openapi_connection_ids.return_value = []

        with pytest.raises(ValueError, match="linked to connections"):
            await svc.delete(config_id)

    async def test_delete_raises_if_linked_openapi_connection(self):
        svc, repo, _ = _make_service()
        config_id = uuid4()
        repo.get_linked_instance_ids.return_value = []
        repo.get_linked_openapi_connection_ids.return_value = ["conn-1"]

        with pytest.raises(ValueError, match="conn-1"):
            await svc.delete(config_id)

    async def test_delete_removes_credentials(self):
        svc, repo, sm = _make_service()
        config_id = uuid4()

        cfg = _make_config(AUTH_TYPE_BEARER)
        cfg.secret_key = "mcp_auth_cred:some-id"  # noqa: S105
        repo.get_linked_instance_ids.return_value = []
        repo.get_linked_openapi_connection_ids.return_value = []
        repo.get.return_value = cfg
        repo.delete.return_value = True

        result = await svc.delete(config_id)

        sm.delete_secret.assert_called_once_with(cfg.secret_key)
        assert result is True


# ---------------------------------------------------------------------------
# get_for_use — who may attach an auth config to a connection/instance
# ---------------------------------------------------------------------------


def _service_as(
    user_id: str, workspace_id: str = "ws-acme", admin_workspaces: list[str] | None = None
) -> tuple[MCPAuthService, AsyncMock]:
    repo = AsyncMock()
    repo.user_context = UserContext(
        user_id=user_id, workspace_id=workspace_id, admin_workspaces=admin_workspaces
    )
    return MCPAuthService(repo, AsyncMock()), repo


@pytest.mark.asyncio
class TestGetForUse:
    """Only the config's creator or a workspace admin may put it to use (#486)."""

    @pytest.fixture(autouse=True)
    def _authz(self) -> None:
        register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

    async def test_another_member_is_refused(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        svc, repo = _service_as("member-b", admin_workspaces=[])
        repo.get.return_value = config

        with pytest.raises(AuthConfigAccessDeniedError):
            await svc.get_for_use(config.id)

    async def test_the_creator_may_use_it(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        svc, repo = _service_as("member-a", admin_workspaces=[])
        repo.get.return_value = config

        assert await svc.get_for_use(config.id) is config

    async def test_a_workspace_admin_may_use_it(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        svc, repo = _service_as("admin", admin_workspaces=["ws-acme"])
        repo.get.return_value = config

        assert await svc.get_for_use(config.id) is config

    async def test_admin_of_another_workspace_is_refused(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        svc, repo = _service_as("admin", workspace_id="ws-acme", admin_workspaces=["ws-other"])
        repo.get.return_value = config

        with pytest.raises(AuthConfigAccessDeniedError):
            await svc.get_for_use(config.id)

    async def test_not_found_raises_value_error(self):
        svc, repo = _service_as("member-a", admin_workspaces=[])
        repo.get.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await svc.get_for_use(uuid4())


@pytest.mark.asyncio
class TestAuthConfigAccessChecker:
    """The resolver built for OpenAPI connections enforces the same rule."""

    @pytest.fixture(autouse=True)
    def _authz(self) -> None:
        register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())

    async def test_checker_refuses_a_foreign_config(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        repo = AsyncMock()
        repo.user_context = UserContext(
            user_id="member-b", workspace_id="ws-acme", admin_workspaces=[]
        )
        repo.get.return_value = config
        repo_factory = MagicMock()
        repo_factory.create_repository.return_value = repo

        checker = build_auth_config_access_checker(repo_factory, AsyncMock())

        with pytest.raises(AuthConfigAccessDeniedError):
            await checker(config.id)

    async def test_checker_allows_the_creator(self):
        config = _make_config(AUTH_TYPE_BEARER)
        config.created_by = "member-a"
        repo = AsyncMock()
        repo.user_context = UserContext(
            user_id="member-a", workspace_id="ws-acme", admin_workspaces=[]
        )
        repo.get.return_value = config
        repo_factory = MagicMock()
        repo_factory.create_repository.return_value = repo

        checker = build_auth_config_access_checker(repo_factory, AsyncMock())

        await checker(config.id)


# ---------------------------------------------------------------------------
# MCPAuthConfig domain model validation
# ---------------------------------------------------------------------------


class TestMCPAuthConfigModel:
    def test_invalid_auth_type_raises(self):
        with pytest.raises(ValueError, match="auth_type"):
            MCPAuthConfig(name="x", auth_type="invalid")

    def test_validate_config_api_key_missing_header_name(self):
        cfg = MCPAuthConfig(name="x", auth_type=AUTH_TYPE_API_KEY, config={})
        with pytest.raises(ValueError, match="header_name"):
            cfg.validate_config()

    def test_validate_config_oauth2_missing_client_id(self):
        cfg = MCPAuthConfig(
            name="x",
            auth_type=AUTH_TYPE_OAUTH2,
            config={"token_url": "https://example.com/token"},
        )
        with pytest.raises(ValueError, match="client_id"):
            cfg.validate_config()

    def test_validate_config_passes_for_valid_api_key(self):
        cfg = MCPAuthConfig(
            name="x",
            auth_type=AUTH_TYPE_API_KEY,
            config={"header_name": "X-Key"},
        )
        cfg.validate_config()  # Should not raise
