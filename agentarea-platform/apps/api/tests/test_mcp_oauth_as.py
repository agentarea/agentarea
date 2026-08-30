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


HYDRA = "https://oauth.example.com"
HYDRA_ADMIN = "http://hydra-admin.internal:4445"

# Trimmed to the fields these tests reason about; the point of the passthrough
# is precisely that fields nobody enumerated still reach the client.
HYDRA_DOC = {
    "issuer": f"{HYDRA}/",
    "authorization_endpoint": f"{HYDRA}/oauth2/auth",
    "token_endpoint": f"{HYDRA}/oauth2/token",
    "revocation_endpoint": f"{HYDRA}/oauth2/revoke",
    "jwks_uri": f"{HYDRA}/.well-known/jwks.json",
    "userinfo_endpoint": f"{HYDRA}/userinfo",
    "end_session_endpoint": f"{HYDRA}/oauth2/sessions/logout",
    "registration_endpoint": f"{HYDRA}/oauth2/register",
    "scopes_supported": ["offline_access", "offline", "openid"],
    "subject_types_supported": ["public"],
    "id_token_signing_alg_values_supported": ["RS256"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "code_challenge_methods_supported": ["S256"],
}


class _Settings:
    """Minimal stand-in for the app settings the endpoint reads."""

    class app:  # noqa: N801 - mirrors the settings attribute name
        API_BASE_URL = API_BASE

    class mcp:  # noqa: N801 - mirrors the settings attribute name
        HYDRA_PUBLIC_URL = HYDRA
        HYDRA_ADMIN_URL = HYDRA_ADMIN
        HYDRA_BROWSER_URL = HYDRA
        MCP_OAUTH_SCOPES = "openid offline_access"


class _FakeResponse:
    def __init__(self, payload=None, content=b"{}", status_code=200):
        self._payload = payload
        self.content = content
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient, recording what was sent upstream."""

    sent: list = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return _FakeResponse(payload=HYDRA_DOC)

    async def post(self, url, content=None, **kwargs):
        type(self).sent.append(json.loads(content))
        return _FakeResponse(content=b'{"client_id":"x"}')


@pytest.fixture
def hydra(monkeypatch):
    """Point the endpoints at a stubbed Hydra and settings."""
    monkeypatch.setattr(mcp_oauth_as, "get_settings", lambda: _Settings())
    monkeypatch.setattr(mcp_oauth_as.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(_FakeAsyncClient, "sent", [])

    app = FastAPI()
    app.include_router(mcp_oauth_as.oauth_as_router)
    return TestClient(app)


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

    def test_client_mcp_instance_advertises_its_own_resource(self, client):
        # Each client's endpoint is its own resource. A harness that follows
        # RFC 9728 rejects a document whose `resource` disagrees with the URL it
        # is talking to, so /client-mcp/<id> cannot be answered with /client-mcp
        # (let alone /mcp) — that mismatch is what broke `codex mcp login`.
        client_id = "74dfa41a-1736-4ab1-a470-2e2d4c4e56c8"

        response = client.get(f"/.well-known/oauth-protected-resource/client-mcp/{client_id}")

        assert response.status_code == 200
        assert response.json()["resource"] == f"{API_BASE}/client-mcp/{client_id}"

    def test_client_mcp_subpath_must_name_an_instance(self, client):
        # Still no catch-all: only a client id is a resource under /client-mcp.
        assert (
            client.get("/.well-known/oauth-protected-resource/client-mcp/not-a-uuid").status_code
            == 404
        )
        assert (
            client.get(
                "/.well-known/oauth-protected-resource/client-mcp/"
                "74dfa41a-1736-4ab1-a470-2e2d4c4e56c8/extra"
            ).status_code
            == 404
        )

    def test_unknown_resource_path_is_not_served(self, client):
        # A catch-all would answer for resources this API does not protect.
        assert client.get("/.well-known/oauth-protected-resource/nope").status_code == 404


class TestAuthorizationServerMetadata:
    """What survives the trip from Hydra's document to the client's (RFC 8414).

    The document is a passthrough, not a hand-written subset: a field nobody
    thought to enumerate must still reach the client. `scopes_supported` is the
    one that bit us — without it a client never learns `offline_access` exists,
    never asks for it, and so never gets a refresh token; the access token then
    expires an hour later and the user has to redo the browser flow.
    """

    def test_advertises_the_scopes_hydra_supports(self, hydra):
        metadata = hydra.get("/.well-known/oauth-authorization-server").json()

        assert metadata["scopes_supported"] == ["offline_access", "offline", "openid"]

    def test_passes_through_fields_it_does_not_rewrite(self, hydra):
        metadata = hydra.get("/.well-known/oauth-authorization-server").json()

        # Required by OIDC Discovery, and previously dropped on the floor.
        assert metadata["subject_types_supported"] == ["public"]
        assert metadata["id_token_signing_alg_values_supported"] == ["RS256"]

    def test_rewrites_the_endpoints_we_proxy(self, hydra):
        metadata = hydra.get("/.well-known/oauth-authorization-server").json()

        assert metadata["authorization_endpoint"] == f"{API_BASE}/oauth2/auth"
        assert metadata["token_endpoint"] == f"{API_BASE}/oauth2/token"
        assert metadata["revocation_endpoint"] == f"{API_BASE}/oauth2/revoke"
        assert metadata["jwks_uri"] == f"{API_BASE}/.well-known/jwks.json"

    def test_leaves_endpoints_we_do_not_proxy_on_hydra(self, hydra):
        # Rewriting a path we do not serve would hand clients a 404.
        metadata = hydra.get("/.well-known/oauth-authorization-server").json()

        assert metadata["userinfo_endpoint"] == f"{HYDRA}/userinfo"
        assert metadata["end_session_endpoint"] == f"{HYDRA}/oauth2/sessions/logout"

    def test_claims_the_issuer_and_its_own_registration_endpoint(self, hydra):
        metadata = hydra.get("/.well-known/oauth-authorization-server").json()

        assert metadata["issuer"] == API_BASE
        assert metadata["registration_endpoint"] == f"{API_BASE}/oauth2/register"


class TestDynamicClientRegistration:
    """A client registered without the refresh grant can only ever re-auth."""

    def test_registers_the_client_for_refresh_by_default(self, hydra):
        hydra.post("/oauth2/register", json={"client_name": "probe"})

        sent = _FakeAsyncClient.sent[-1]
        assert "refresh_token" in sent["grant_types"]
        assert "authorization_code" in sent["grant_types"]
        assert "offline_access" in sent["scope"].split()

    def test_respects_grant_types_the_client_asked_for(self, hydra):
        hydra.post(
            "/oauth2/register",
            json={"client_name": "probe", "grant_types": ["authorization_code"]},
        )

        assert _FakeAsyncClient.sent[-1]["grant_types"] == ["authorization_code"]
