"""Unit tests for MCPOAuthClientService.

The service is the *client* side of the MCP OAuth spec: discovery,
Dynamic Client Registration, PKCE auth URL building, and token exchange.
We pin its public surface against the spec (RFC 8414/9728/7591/8707 +
OAuth 2.1 PKCE) using ``httpx.MockTransport`` so no network calls happen.
"""

from __future__ import annotations

import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from agentarea_mcp.application.oauth_client_service import (
    AuthServerMetadata,
    MCPOAuthClientService,
    MCPOAuthDiscoveryError,
    PKCEPair,
    _parse_resource_metadata_url,
    _parse_scope_from_www_authenticate,
)


# ---------------------------------------------------------------------------
# Helper: redirect httpx clients inside the service to a MockTransport.
# ---------------------------------------------------------------------------

_REAL_ASYNC_CLIENT = httpx.AsyncClient


def _patch_httpx(monkeypatch, handler) -> None:
    transport = httpx.MockTransport(handler)

    class _Client:
        def __init__(self, *_, **__) -> None:
            self._client = _REAL_ASYNC_CLIENT(transport=transport)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, *exc) -> None:
            await self._client.aclose()

    monkeypatch.setattr(
        "agentarea_mcp.application.oauth_client_service.httpx.AsyncClient", _Client
    )


# ---------------------------------------------------------------------------
# PKCE
# ---------------------------------------------------------------------------


class TestPKCE:
    def test_challenge_is_s256_hash_of_verifier(self):
        pair = PKCEPair.generate()
        digest = hashlib.sha256(pair.verifier.encode("ascii")).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        assert pair.challenge == expected
        assert pair.method == "S256"

    def test_each_pair_is_unique(self):
        a, b = PKCEPair.generate(), PKCEPair.generate()
        assert a.verifier != b.verifier
        assert a.challenge != b.challenge


# ---------------------------------------------------------------------------
# WWW-Authenticate parsing
# ---------------------------------------------------------------------------


class TestWwwAuthenticateParsing:
    def test_resource_metadata_extracted(self):
        header = (
            'Bearer realm="example", '
            'resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
        )
        assert (
            _parse_resource_metadata_url(header)
            == "https://api.example.com/.well-known/oauth-protected-resource"
        )

    def test_returns_last_resource_metadata_when_multiple(self):
        header = (
            'resource_metadata="https://api.example.com/.well-known/oauth-protected-resource", '
            'resource_metadata="https://api.example.com/.well-known/oauth-protected-resource/mcp"'
        )
        assert _parse_resource_metadata_url(header).endswith("/mcp")

    def test_returns_none_when_missing(self):
        assert _parse_resource_metadata_url('Bearer realm="x"') is None

    def test_scope_extracted(self):
        header = 'Bearer scope="openid profile email"'
        assert _parse_scope_from_www_authenticate(header) == "openid profile email"

    def test_scope_missing_returns_empty(self):
        assert _parse_scope_from_www_authenticate("") == ""


# ---------------------------------------------------------------------------
# AS metadata discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFetchAsMetadata:
    async def test_known_provider_short_circuits_discovery(self, monkeypatch):
        # GitHub is in _KNOWN_PROVIDERS, so no HTTP call should be made.
        def handler(_request):
            raise AssertionError("no HTTP call expected for known providers")

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()

        async with httpx.AsyncClient() as client:
            meta = await svc._fetch_as_metadata(client, "https://github.com/login/oauth")

        assert meta.authorization_endpoint == "https://github.com/login/oauth/authorize"
        assert meta.token_endpoint == "https://github.com/login/oauth/access_token"
        assert meta.registration_endpoint is None  # GitHub has no DCR

    async def test_rfc_8414_metadata_is_used_first(self, monkeypatch):
        responses = {
            "/.well-known/oauth-authorization-server": {
                "issuer": "https://as.example.com",
                "authorization_endpoint": "https://as.example.com/authorize",
                "token_endpoint": "https://as.example.com/token",
                "registration_endpoint": "https://as.example.com/register",
                "scopes_supported": ["openid"],
            }
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=responses[request.url.path])

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()

        async with httpx.AsyncClient() as client:
            meta = await svc._fetch_as_metadata(client, "https://as.example.com")

        assert meta.token_endpoint == "https://as.example.com/token"
        assert meta.registration_endpoint == "https://as.example.com/register"
        assert meta.scopes_supported == ["openid"]

    async def test_falls_back_to_oidc_discovery(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/.well-known/oauth-authorization-server":
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={
                    "issuer": "https://as.example.com",
                    "authorization_endpoint": "https://as.example.com/oidc/authorize",
                    "token_endpoint": "https://as.example.com/oidc/token",
                },
            )

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        async with httpx.AsyncClient() as client:
            meta = await svc._fetch_as_metadata(client, "https://as.example.com")
        assert meta.token_endpoint == "https://as.example.com/oidc/token"

    async def test_raises_when_no_metadata_available(self, monkeypatch):
        def handler(_request):
            return httpx.Response(404)

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        with pytest.raises(MCPOAuthDiscoveryError):
            async with httpx.AsyncClient() as client:
                await svc._fetch_as_metadata(client, "https://as.example.com")


# ---------------------------------------------------------------------------
# Full discover_auth_server flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDiscoverAuthServer:
    async def test_happy_path_uses_resource_metadata_then_as_metadata(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://mcp.example.com/sse":
                return httpx.Response(
                    401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer resource_metadata='
                            '"https://mcp.example.com/.well-known/oauth-protected-resource"'
                        )
                    },
                )
            if url.endswith("/.well-known/oauth-protected-resource"):
                return httpx.Response(
                    200,
                    json={
                        "resource": "https://mcp.example.com/sse",
                        "authorization_servers": ["https://as.example.com"],
                    },
                )
            if url.endswith("/.well-known/oauth-authorization-server"):
                return httpx.Response(
                    200,
                    json={
                        "issuer": "https://as.example.com",
                        "authorization_endpoint": "https://as.example.com/authorize",
                        "token_endpoint": "https://as.example.com/token",
                    },
                )
            raise AssertionError(f"unexpected request: {url}")

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()

        meta = await svc.discover_auth_server("https://mcp.example.com/sse")

        assert meta.token_endpoint == "https://as.example.com/token"
        assert meta.resource == "https://mcp.example.com/sse"

    async def test_accepts_403_auth_challenge(self, monkeypatch):
        """Vercel answers an unauthenticated request with 403, not 401 — discovery
        must still proceed (the status is only a hint to find the metadata URL)."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://mcp.vercel.com":
                return httpx.Response(
                    403,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer resource_metadata='
                            '"https://mcp.vercel.com/.well-known/oauth-protected-resource"'
                        )
                    },
                )
            if url.endswith("/.well-known/oauth-protected-resource"):
                return httpx.Response(
                    200,
                    json={
                        "resource": "https://mcp.vercel.com",
                        "authorization_servers": ["https://as.vercel.com"],
                    },
                )
            if url.endswith("/.well-known/oauth-authorization-server"):
                return httpx.Response(
                    200,
                    json={
                        "issuer": "https://as.vercel.com",
                        "authorization_endpoint": "https://as.vercel.com/authorize",
                        "token_endpoint": "https://as.vercel.com/token",
                    },
                )
            raise AssertionError(f"unexpected request: {url}")

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()

        meta = await svc.discover_auth_server("https://mcp.vercel.com")

        assert meta.token_endpoint == "https://as.vercel.com/token"
        assert meta.resource == "https://mcp.vercel.com"

    async def test_raises_when_initial_response_is_not_an_auth_challenge(self, monkeypatch):
        def handler(_request):
            return httpx.Response(200)

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        with pytest.raises(MCPOAuthDiscoveryError):
            await svc.discover_auth_server("https://mcp.example.com/sse")

    async def test_metadata_403_raises_discovery_error_not_500(self, monkeypatch):
        """Regression: a 403 on the protected-resource metadata (Vercel gates it)
        must become MCPOAuthDiscoveryError, not an unhandled HTTPStatusError/500."""

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://mcp.vercel.com":
                return httpx.Response(403)  # auth challenge, no resource_metadata hint
            if "/.well-known/oauth-protected-resource" in url:
                return httpx.Response(403)  # both path-specific and root are gated
            raise AssertionError(f"unexpected request: {url}")

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        with pytest.raises(MCPOAuthDiscoveryError, match="protected-resource metadata"):
            await svc.discover_auth_server("https://mcp.vercel.com")

    async def test_raises_when_no_authorization_servers_listed(self, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url == "https://mcp.example.com/sse":
                return httpx.Response(
                    401,
                    headers={
                        "WWW-Authenticate": (
                            'Bearer resource_metadata='
                            '"https://mcp.example.com/.well-known/oauth-protected-resource"'
                        )
                    },
                )
            if url.endswith("/.well-known/oauth-protected-resource"):
                return httpx.Response(200, json={"resource": "https://mcp.example.com/sse"})
            raise AssertionError(url)

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        with pytest.raises(MCPOAuthDiscoveryError):
            await svc.discover_auth_server("https://mcp.example.com/sse")


# ---------------------------------------------------------------------------
# Dynamic Client Registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRegisterClient:
    async def test_dcr_returns_client_credentials(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(
                200, json={"client_id": "cid-123", "client_secret": "csecret"}
            )

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
            registration_endpoint="https://as.example.com/register",
        )

        creds = await svc.register_client(meta, "https://app.example.com/callback")

        assert creds.client_id == "cid-123"
        assert creds.client_secret == "csecret"
        body = json.loads(captured["body"])
        assert body["redirect_uris"] == ["https://app.example.com/callback"]
        assert body["token_endpoint_auth_method"] == "none"
        assert body["grant_types"] == ["authorization_code"]

    async def test_dcr_raises_when_registration_endpoint_missing(self):
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://github.com/login/oauth",
            authorization_endpoint="https://github.com/login/oauth/authorize",
            token_endpoint="https://github.com/login/oauth/access_token",
            registration_endpoint=None,
        )
        with pytest.raises(MCPOAuthDiscoveryError):
            await svc.register_client(meta, "https://app.example.com/callback")


# ---------------------------------------------------------------------------
# Authorization URL builder
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl:
    def test_url_contains_pkce_state_and_resource(self):
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
            scopes_supported=["read", "write"],
            resource="https://mcp.example.com/sse",
        )
        pkce = PKCEPair(verifier="v" * 64, challenge="ch", method="S256")

        url = svc.build_authorize_url(
            meta,
            client_id="cid",
            redirect_uri="https://app.example.com/cb",
            pkce=pkce,
            state="state-xyz",
        )

        params = parse_qs(urlparse(url).query)
        assert params["response_type"] == ["code"]
        assert params["client_id"] == ["cid"]
        assert params["redirect_uri"] == ["https://app.example.com/cb"]
        assert params["code_challenge"] == ["ch"]
        assert params["code_challenge_method"] == ["S256"]
        assert params["state"] == ["state-xyz"]
        # offline_access is always appended so the AS issues a refresh_token.
        assert params["scope"] == ["read write offline_access"]
        assert params["resource"] == ["https://mcp.example.com/sse"]

    def test_offline_access_always_requested(self):
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
        )
        pkce = PKCEPair(verifier="v", challenge="c")
        url = svc.build_authorize_url(
            meta, client_id="cid", redirect_uri="https://app/cb", pkce=pkce, state="s"
        )
        params = parse_qs(urlparse(url).query)
        assert params["scope"] == ["offline_access"]

    def test_explicit_scopes_override_metadata_scopes(self):
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
            scopes_supported=["should-not-be-used"],
        )
        pkce = PKCEPair(verifier="v", challenge="c")

        url = svc.build_authorize_url(
            meta,
            client_id="cid",
            redirect_uri="https://app.example.com/cb",
            pkce=pkce,
            state="s",
            scopes=["custom"],
        )

        assert "scope=custom" in url


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestExchangeCode:
    async def test_posts_grant_with_pkce_and_returns_token_response(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            captured["url"] = str(request.url)
            return httpx.Response(
                200,
                json={
                    "access_token": "at-1",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                    "refresh_token": "rt-1",
                },
            )

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
        )

        tokens = await svc.exchange_code(
            meta,
            code="auth-code",
            client_id="cid",
            redirect_uri="https://app.example.com/cb",
            code_verifier="ver",
        )

        assert tokens["access_token"] == "at-1"
        assert tokens["refresh_token"] == "rt-1"
        body = captured["body"]
        assert "grant_type=authorization_code" in body
        assert "code=auth-code" in body
        assert "code_verifier=ver" in body
        assert captured["url"] == "https://as.example.com/token"

    async def test_includes_client_secret_when_provided(self, monkeypatch):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content.decode()
            return httpx.Response(200, json={"access_token": "t"})

        _patch_httpx(monkeypatch, handler)
        svc = MCPOAuthClientService()
        meta = AuthServerMetadata(
            issuer="https://as.example.com",
            authorization_endpoint="https://as.example.com/authorize",
            token_endpoint="https://as.example.com/token",
        )

        await svc.exchange_code(
            meta,
            code="c",
            client_id="cid",
            redirect_uri="https://app.example.com/cb",
            code_verifier="ver",
            client_secret="shh",
        )

        assert "client_secret=shh" in captured["body"]
