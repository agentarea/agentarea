"""Unit tests for MCPAuthService."""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from agentarea_mcp.application.auth_service import MCPAuthService, OAuthReauthRequiredError
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
    c = _make_config(AUTH_TYPE_OAUTH2, secret_key="k")
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
        with pytest.raises(ValueError):
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
    async def test_api_key_injects_custom_header(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"header_value": "MY_SECRET"})

        config = _make_config(
            AUTH_TYPE_API_KEY,
            config={"header_name": "X-My-Key"},
            secret_key="some_key",
        )
        headers = await svc.get_auth_headers(config)
        assert headers == {"X-My-Key": "MY_SECRET"}

    async def test_api_key_uses_default_header_name(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"header_value": "VAL"})

        config = _make_config(AUTH_TYPE_API_KEY, config={}, secret_key="k")
        headers = await svc.get_auth_headers(config)
        assert "X-API-Key" in headers

    async def test_bearer_injects_authorization_header(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = json.dumps({"token": "abc123"})

        config = _make_config(AUTH_TYPE_BEARER, secret_key="k")
        headers = await svc.get_auth_headers(config)
        assert headers == {"Authorization": "Bearer abc123"}

    async def test_missing_secret_returns_empty(self):
        svc, _, sm = _make_service()
        sm.get_secret.return_value = None

        config = _make_config(AUTH_TYPE_API_KEY, config={"header_name": "X-Key"})
        headers = await svc.get_auth_headers(config)
        assert headers.get("X-Key") == ""


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

        with pytest.raises(ValueError, match="linked to instances"):
            await svc.delete(config_id)

    async def test_delete_removes_credentials(self):
        svc, repo, sm = _make_service()
        config_id = uuid4()

        cfg = _make_config(AUTH_TYPE_BEARER)
        cfg.secret_key = "mcp_auth_cred:some-id"
        repo.get_linked_instance_ids.return_value = []
        repo.get.return_value = cfg
        repo.delete.return_value = True

        result = await svc.delete(config_id)

        sm.delete_secret.assert_called_once_with(cfg.secret_key)
        assert result is True


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
