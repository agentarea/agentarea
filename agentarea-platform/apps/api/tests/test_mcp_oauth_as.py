"""Tests for the Hydra OAuth2 proxy path hardening and AS advertisement.

The proxy forwards /oauth2/{path} to a fixed, config-driven Hydra host. The host
cannot be changed by the caller, but the user-controlled subpath must not be able
to traverse out of /oauth2/ on that host (partial-SSRF / path-traversal hardening).
"""

import json

import pytest
from agentarea_api.api.v1 import mcp_oauth_as
from agentarea_api.api.v1.mcp_oauth_as import _is_safe_oauth2_subpath
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_BASE = "https://api.example.com"


class _Settings:
    """Minimal stand-in for the app settings the endpoint reads."""

    class app:  # noqa: N801 - mirrors the settings attribute name
        API_BASE_URL = API_BASE


class TestOAuth2SubpathValidation:
    def test_allows_legitimate_oauth2_paths(self):
        for p in ["token", "revoke", "introspect", "sessions/logout", "userinfo", "device.well"]:
            assert _is_safe_oauth2_subpath(p), p

    def test_rejects_parent_traversal(self):
        for p in ["../admin/clients", "..", "token/../../admin", "a/../../b", "sub/.."]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_backslash_and_control_chars(self):
        for p in ["foo\\bar", "tok\nen", "tok\ren", "a\x00b"]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_url_authority_injection(self):
        # Characters that could confuse URL parsing into changing the authority.
        for p in ["@evil.com/path", "evil.com:8080/x", "host/with space"]:
            assert not _is_safe_oauth2_subpath(p), p

    def test_rejects_empty(self):
        assert not _is_safe_oauth2_subpath("")


class TestProtectedResourceMetadata:
    """Which authorization server the resource advertises (RFC 9728)."""

    @staticmethod
    def _patch(monkeypatch, discovery):
        monkeypatch.setattr(mcp_oauth_as, "get_settings", lambda: _Settings())

        async def _discovery():
            return discovery

        monkeypatch.setattr(mcp_oauth_as, "_hydra_discovery", _discovery)

    @staticmethod
    async def _metadata():
        response = await mcp_oauth_as.oauth_protected_resource_metadata()
        return json.loads(response.body)

    async def test_advertises_hydra_when_it_exposes_dcr(self, monkeypatch):
        # Hydra mints the tokens, so its issuer is what clients validate `iss`
        # against — advertising ourselves would fail that check.
        self._patch(
            monkeypatch,
            {
                "issuer": "https://oauth.example.com/",
                "registration_endpoint": f"{API_BASE}/oauth2/register",
            },
        )

        metadata = await self._metadata()

        assert metadata["authorization_servers"] == ["https://oauth.example.com"]
        assert metadata["resource"] == f"{API_BASE}/mcp"

    async def test_falls_back_to_self_when_hydra_has_no_dcr(self, monkeypatch):
        # Without a registration endpoint MCP clients cannot register, so keep
        # pointing at our own AS shim rather than breaking them.
        self._patch(monkeypatch, {"issuer": "https://oauth.example.com"})

        assert (await self._metadata())["authorization_servers"] == [API_BASE]

    async def test_falls_back_to_self_when_hydra_unreachable(self, monkeypatch):
        self._patch(monkeypatch, None)

        assert (await self._metadata())["authorization_servers"] == [API_BASE]


class TestProtectedResourceMetadataLocations:
    """Where the document is retrievable from (RFC 9728 §3.1).

    The resource identifier is path-scoped (``<API>/mcp``), so the metadata URL
    a client derives from it carries that path as a suffix. Serving only the
    root location breaks any client that derives the URL instead of following
    the one in ``WWW-Authenticate``.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(mcp_oauth_as, "get_settings", lambda: _Settings())

        async def _discovery():
            return None

        monkeypatch.setattr(mcp_oauth_as, "_hydra_discovery", _discovery)

        app = FastAPI()
        app.include_router(mcp_oauth_as.oauth_as_router)
        return TestClient(app)

    def test_served_at_the_root_location(self, client):
        response = client.get("/.well-known/oauth-protected-resource")

        assert response.status_code == 200
        assert response.json()["resource"] == f"{API_BASE}/mcp"

    def test_served_at_the_path_suffixed_location(self, client):
        response = client.get("/.well-known/oauth-protected-resource/mcp")

        assert response.status_code == 200
        assert response.json()["resource"] == f"{API_BASE}/mcp"

    def test_client_mcp_advertises_its_own_resource(self, client):
        # A separate protected resource: same authorization server, different
        # canonical URI, so it must not claim to be /mcp.
        response = client.get("/.well-known/oauth-protected-resource/client-mcp")

        assert response.status_code == 200
        assert response.json()["resource"] == f"{API_BASE}/client-mcp"

    def test_unknown_resource_path_is_not_served(self, client):
        # A catch-all would answer for resources this API does not protect.
        assert client.get("/.well-known/oauth-protected-resource/nope").status_code == 404
