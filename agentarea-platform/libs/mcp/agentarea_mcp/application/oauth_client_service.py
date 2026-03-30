"""MCP OAuth Client — implements the client-side of the MCP authorization spec.

When AgentArea connects to a remote MCP server that requires OAuth (e.g. GitHub
Copilot), this service handles the discovery → registration → authorization flow:

    1. discover_auth_server(mcp_url)  — RFC 9728 + RFC 8414 discovery
    2. register_client(as_metadata)   — RFC 7591 Dynamic Client Registration
    3. build_authorize_url(...)       — OAuth 2.1 + PKCE (S256)
    4. exchange_code(...)             — Authorization code → access token

References:
    - MCP Authorization: https://modelcontextprotocol.io/specification/draft/basic/authorization
    - RFC 9728: OAuth 2.0 Protected Resource Metadata
    - RFC 8414: OAuth 2.0 Authorization Server Metadata Discovery
    - RFC 7591: OAuth 2.0 Dynamic Client Registration
    - RFC 8707: Resource Indicators for OAuth 2.0
"""

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

logger = logging.getLogger(__name__)

# Timeout for outbound HTTP calls during discovery / token exchange
_HTTP_TIMEOUT = httpx.Timeout(15)

# Known OAuth providers that don't support RFC 8414 AS metadata discovery.
# Maps AS base URL → hardcoded metadata.
_KNOWN_PROVIDERS: dict[str, dict[str, str]] = {
    "https://github.com/login/oauth": {
        "authorization_endpoint": "https://github.com/login/oauth/authorize",
        "token_endpoint": "https://github.com/login/oauth/access_token",
        "registration_endpoint": "",  # GitHub doesn't support DCR
    },
}


@dataclass
class AuthServerMetadata:
    """Parsed OAuth 2.0 Authorization Server metadata (RFC 8414)."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None
    scopes_supported: list[str] = field(default_factory=list)
    code_challenge_methods_supported: list[str] = field(default_factory=list)
    resource: str = ""  # The MCP server's resource identifier


@dataclass
class PKCEPair:
    """PKCE code_verifier + code_challenge (S256)."""

    verifier: str
    challenge: str
    method: str = "S256"

    @staticmethod
    def generate() -> "PKCEPair":
        verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return PKCEPair(verifier=verifier, challenge=challenge)


@dataclass
class OAuthClientCredentials:
    """Result of Dynamic Client Registration."""

    client_id: str
    client_secret: str | None = None


class MCPOAuthClientService:
    """Client-side MCP authorization: discovery, DCR, PKCE auth flow."""

    async def discover_auth_server(self, mcp_url: str) -> AuthServerMetadata:
        """Discover the authorization server for a remote MCP endpoint.

        Steps:
            1. GET mcp_url → expect 401 with WWW-Authenticate header
            2. Parse resource_metadata URL from the header
            3. Fetch Protected Resource Metadata (RFC 9728)
            4. Fetch Authorization Server Metadata (RFC 8414)
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # Step 1: Hit the MCP endpoint to get the 401 challenge
            resp = await client.get(mcp_url, follow_redirects=True)

            if resp.status_code != 401:
                raise MCPOAuthDiscoveryError(
                    f"Expected 401 from {mcp_url}, got {resp.status_code}"
                )

            www_auth = resp.headers.get("www-authenticate", "")
            logger.info("WWW-Authenticate header: %s", www_auth)
            resource_metadata_url = _parse_resource_metadata_url(www_auth)
            scope_hint = _parse_scope_from_www_authenticate(www_auth)

            if not resource_metadata_url:
                # Fallback: try path-specific then root well-known
                parsed = urlparse(mcp_url)
                path = parsed.path.rstrip("/")
                resource_metadata_url = (
                    f"{parsed.scheme}://{parsed.netloc}"
                    f"/.well-known/oauth-protected-resource{path}"
                )
            logger.info("Using resource_metadata_url: %s", resource_metadata_url)

            # Step 2: Fetch Protected Resource Metadata (RFC 9728)
            pr_resp = await client.get(resource_metadata_url)
            if pr_resp.status_code == 404:
                # Try root well-known as last resort
                parsed = urlparse(mcp_url)
                root_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource"
                logger.info("Path-specific metadata 404, trying root: %s", root_url)
                pr_resp = await client.get(root_url)
            pr_resp.raise_for_status()
            pr_meta = pr_resp.json()

            resource = pr_meta.get("resource", mcp_url)
            auth_servers = pr_meta.get("authorization_servers", [])
            if not auth_servers:
                raise MCPOAuthDiscoveryError(
                    f"No authorization_servers in protected resource metadata at {resource_metadata_url}"
                )

            as_base = auth_servers[0].rstrip("/")

            # Step 3: Fetch Authorization Server Metadata (RFC 8414)
            # Try standard path first, then OpenID Connect fallback
            as_meta = await self._fetch_as_metadata(client, as_base)

            as_meta.resource = resource
            if scope_hint and not as_meta.scopes_supported:
                as_meta.scopes_supported = scope_hint.split()

            return as_meta

    async def _fetch_as_metadata(
        self, client: httpx.AsyncClient, as_base: str
    ) -> AuthServerMetadata:
        """Try known providers, then RFC 8414, then OIDC discovery to get AS metadata."""
        # Check known providers that don't support standard discovery
        known = _KNOWN_PROVIDERS.get(as_base)
        if known:
            logger.info("Using known provider config for %s", as_base)
            return AuthServerMetadata(
                issuer=as_base,
                authorization_endpoint=known["authorization_endpoint"],
                token_endpoint=known["token_endpoint"],
                registration_endpoint=known.get("registration_endpoint") or None,
            )

        for path in (
            "/.well-known/oauth-authorization-server",
            "/.well-known/openid-configuration",
        ):
            try:
                resp = await client.get(f"{as_base}{path}")
                if resp.status_code == 200:
                    data = resp.json()
                    return AuthServerMetadata(
                        issuer=data.get("issuer", as_base),
                        authorization_endpoint=data["authorization_endpoint"],
                        token_endpoint=data["token_endpoint"],
                        registration_endpoint=data.get("registration_endpoint"),
                        scopes_supported=data.get("scopes_supported", []),
                        code_challenge_methods_supported=data.get(
                            "code_challenge_methods_supported", ["S256"]
                        ),
                    )
            except (httpx.HTTPError, KeyError):
                continue

        raise MCPOAuthDiscoveryError(
            f"Could not fetch AS metadata from {as_base}"
        )

    async def register_client(
        self,
        as_metadata: AuthServerMetadata,
        redirect_uri: str,
        client_name: str = "AgentArea",
    ) -> OAuthClientCredentials:
        """Dynamic Client Registration (RFC 7591) with the remote AS.

        Returns client_id (and optionally client_secret) for the authorization flow.
        """
        if not as_metadata.registration_endpoint:
            raise MCPOAuthDiscoveryError(
                "Authorization server does not support Dynamic Client Registration "
                "(no registration_endpoint). Pre-registered credentials required."
            )

        payload = {
            "client_name": client_name,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # Public client (PKCE-only)
            "application_type": "web",
        }

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                as_metadata.registration_endpoint,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()

        return OAuthClientCredentials(
            client_id=data["client_id"],
            client_secret=data.get("client_secret"),
        )

    def build_authorize_url(
        self,
        as_metadata: AuthServerMetadata,
        client_id: str,
        redirect_uri: str,
        pkce: PKCEPair,
        state: str,
        scopes: list[str] | None = None,
    ) -> str:
        """Build the OAuth 2.1 authorization URL with PKCE and resource indicator."""
        scope_list = scopes or as_metadata.scopes_supported
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": pkce.challenge,
            "code_challenge_method": pkce.method,
        }
        if scope_list:
            params["scope"] = " ".join(scope_list)
        if as_metadata.resource:
            params["resource"] = as_metadata.resource

        return f"{as_metadata.authorization_endpoint}?{urlencode(params)}"

    async def exchange_code(
        self,
        as_metadata: AuthServerMetadata,
        code: str,
        client_id: str,
        redirect_uri: str,
        code_verifier: str,
        client_secret: str | None = None,
    ) -> dict[str, Any]:
        """Exchange authorization code for tokens using PKCE verifier.

        Returns the full token response dict (access_token, token_type,
        expires_in, refresh_token, scope, etc.).
        """
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        if client_secret:
            data["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(
                as_metadata.token_endpoint,
                data=data,
                headers={"Accept": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()


class MCPOAuthDiscoveryError(Exception):
    """Raised when MCP OAuth discovery or registration fails."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_resource_metadata_url(www_authenticate: str) -> str | None:
    """Extract resource_metadata URL from WWW-Authenticate header.

    Some servers (e.g. Sentry) include multiple resource_metadata values —
    a root one and a path-specific one.  We return the *last* (most specific).
    """
    result: str | None = None
    for part in www_authenticate.split(","):
        part = part.strip()
        if "resource_metadata=" in part:
            value = part.split("resource_metadata=", 1)[1].strip().strip('"')
            result = value
    return result


def _parse_scope_from_www_authenticate(www_authenticate: str) -> str:
    """Extract scope from WWW-Authenticate header."""
    for part in www_authenticate.split(","):
        part = part.strip()
        if part.startswith("scope=") or "scope=" in part:
            value = part.split("scope=", 1)[1].strip().strip('"')
            return value
    return ""
