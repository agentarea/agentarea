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
from typing import Any, Literal
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

# Hosts allowed to advertise a plain-http endpoint — the same carve-out
# mcp_oauth_as.py uses for native-client redirect_uris.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _validate_endpoint_url(url: str, field: str) -> str:
    """Reject an AS/protected-resource metadata endpoint the browser could act on.

    A malicious or compromised MCP server controls every URL in its own AS
    metadata. authorization_endpoint flows straight into build_authorize_url(),
    which the frontend then navigates the browser to — a `javascript:` value
    there is a stored XSS (#482). token_endpoint and registration_endpoint are
    POSTed to by this service, so a scheme other than https is an SSRF-adjacent
    risk even though the browser never sees them directly.
    """
    parsed = urlparse(url)
    is_loopback = parsed.hostname in _LOOPBACK_HOSTS
    if parsed.scheme != "https" and not is_loopback:
        raise MCPOAuthDiscoveryError(
            f"Authorization server {field} {url!r} must use https "
            "(or http on a loopback host for local development)"
        )
    return url


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
    # Whether the AS itself listed offline_access. Tracked separately from
    # scopes_supported, which discovery replaces with the resource's scopes.
    offline_access_supported: bool = False


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


@dataclass
class OAuthCapability:
    """Whether a remote MCP server can be authorized, and what it takes.

    ``ready`` — the provider supports dynamic registration, so Connect runs on
    its own. ``oauth_app_required`` — it does not, so the workspace brings an
    OAuth app it registered with the provider. ``unsupported`` — no OAuth
    discovery here; ``detail`` says why.
    """

    status: Literal["ready", "oauth_app_required", "unsupported"]
    detail: str = ""
    metadata: AuthServerMetadata | None = None

    @property
    def advertises_oauth(self) -> bool:
        return self.status != "unsupported"


def oauth_app_required_detail(issuer: str) -> str:
    return (
        f"{issuer} does not support Dynamic Client Registration (RFC 7591), so AgentArea "
        "cannot register itself. Register an OAuth app with this provider and connect with "
        "its client ID and secret."
    )


class MCPOAuthClientService:
    """Client-side MCP authorization: discovery, DCR, PKCE auth flow."""

    async def assess(self, mcp_url: str) -> OAuthCapability:
        """Answer "can this server be authorized, and with what" in one place.

        Every caller that decides whether to offer Connect — the preflight
        endpoint, the create page's auth detection — reads this, so a server
        cannot be "OAuth" on one screen and "open" on the next.
        """
        try:
            metadata = await self.discover_auth_server(mcp_url)
        except MCPOAuthDiscoveryError as exc:
            return OAuthCapability(status="unsupported", detail=str(exc))
        except httpx.HTTPError as exc:
            logger.info("OAuth discovery could not reach %s", mcp_url, exc_info=True)
            return OAuthCapability(status="unsupported", detail=f"Could not reach {mcp_url}: {exc}")
        if metadata.registration_endpoint:
            return OAuthCapability(status="ready", metadata=metadata)
        return OAuthCapability(
            status="oauth_app_required",
            detail=oauth_app_required_detail(metadata.issuer),
            metadata=metadata,
        )

    async def discover_auth_server(self, mcp_url: str) -> AuthServerMetadata:
        """Discover the authorization server for a remote MCP endpoint.

        Steps:
            1. GET mcp_url → read a WWW-Authenticate challenge if the server sends one
            2. Parse resource_metadata URL from the header
            3. Fetch Protected Resource Metadata (RFC 9728)
            4. Fetch Authorization Server Metadata (RFC 8414)
        """
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            # Step 1: Probe the MCP endpoint for an auth challenge. The challenge is
            # only a shortcut to the metadata URL, never a precondition: servers
            # answer an unauthenticated GET with 401 (RFC 9728), 403 (Vercel), or
            # 405 (Google's Gmail MCP is POST-only), and a server that lists tools
            # without auth sends no challenge at all. Any of those still publish
            # protected-resource metadata at the well-known paths below, so treat a
            # missing challenge as a missing hint rather than a dead end.
            resp = await client.get(mcp_url, follow_redirects=True)

            www_auth = resp.headers.get("www-authenticate", "")
            logger.info(
                "Auth challenge probe: HTTP %s, WWW-Authenticate: %s",
                resp.status_code,
                www_auth or "(none)",
            )
            resource_metadata_url = _parse_resource_metadata_url(www_auth)
            scope_hint = _parse_scope_from_www_authenticate(www_auth)

            if not resource_metadata_url:
                # Fallback: try path-specific then root well-known
                parsed = urlparse(mcp_url)
                path = parsed.path.rstrip("/")
                resource_metadata_url = (
                    f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{path}"
                )
            logger.info("Using resource_metadata_url: %s", resource_metadata_url)

            # Step 2: Fetch Protected Resource Metadata (RFC 9728). If the
            # path-specific URL isn't served (404) or is access-restricted
            # (401/403 — some hosts, e.g. Vercel, gate it), fall back to the root
            # well-known before giving up.
            pr_resp = await client.get(resource_metadata_url)
            if pr_resp.status_code in (401, 403, 404):
                parsed = urlparse(mcp_url)
                root_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource"
                if root_url != resource_metadata_url:
                    logger.info(
                        "Protected-resource metadata HTTP %s at %s, trying root: %s",
                        pr_resp.status_code,
                        resource_metadata_url,
                        root_url,
                    )
                    pr_resp = await client.get(root_url)
            if pr_resp.status_code != 200:
                # Don't let raise_for_status() surface as an unhandled 500 — the
                # server just doesn't support standard OAuth discovery for us.
                raise MCPOAuthDiscoveryError(
                    f"Could not fetch OAuth protected-resource metadata for {mcp_url} "
                    f"(HTTP {pr_resp.status_code}). The server may not support automated "
                    f"OAuth discovery."
                )
            try:
                pr_meta = pr_resp.json()
            except ValueError as exc:
                # A 200 that isn't JSON is a server answering something else at the
                # well-known path (an SPA index, an error page) — the same "no
                # discovery here" outcome as a non-200, not an unhandled 500.
                raise MCPOAuthDiscoveryError(
                    f"OAuth protected-resource metadata at {resource_metadata_url} is not "
                    f"valid JSON. The server may not support automated OAuth discovery."
                ) from exc
            if not isinstance(pr_meta, dict):
                raise MCPOAuthDiscoveryError(
                    f"OAuth protected-resource metadata at {resource_metadata_url} is not "
                    f"an object. The server may not support automated OAuth discovery."
                )

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
            # Scope precedence: the resource's own RFC 9728 list, then the
            # challenge hint, then whatever the AS advertises. The AS list is
            # generic (openid/email/profile) and for some providers — Google —
            # it is the only one present, so a token minted from it carries no
            # access to the MCP server at all.
            resource_scopes = pr_meta.get("scopes_supported") or []
            if isinstance(resource_scopes, list):
                resource_scopes = [
                    str(scope) for scope in resource_scopes if isinstance(scope, str)
                ]
            else:
                resource_scopes = []
            if resource_scopes:
                as_meta.scopes_supported = resource_scopes
            elif scope_hint:
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
                authorization_endpoint=_validate_endpoint_url(
                    known["authorization_endpoint"], "authorization_endpoint"
                ),
                token_endpoint=_validate_endpoint_url(known["token_endpoint"], "token_endpoint"),
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
                    advertised = data.get("scopes_supported") or []
                    registration_endpoint = data.get("registration_endpoint")
                    return AuthServerMetadata(
                        issuer=data.get("issuer", as_base),
                        authorization_endpoint=_validate_endpoint_url(
                            data["authorization_endpoint"], "authorization_endpoint"
                        ),
                        token_endpoint=_validate_endpoint_url(
                            data["token_endpoint"], "token_endpoint"
                        ),
                        registration_endpoint=(
                            _validate_endpoint_url(registration_endpoint, "registration_endpoint")
                            if registration_endpoint
                            else None
                        ),
                        scopes_supported=list(advertised),
                        code_challenge_methods_supported=data.get(
                            "code_challenge_methods_supported", ["S256"]
                        ),
                        offline_access_supported="offline_access" in advertised,
                    )
            except (httpx.HTTPError, KeyError):
                continue

        raise MCPOAuthDiscoveryError(f"Could not fetch AS metadata from {as_base}")

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
        scope_list = list(scopes or as_metadata.scopes_supported or [])
        # Request offline_access when the AS advertises it, so it issues a
        # refresh_token; without one, providers like Vercel return a ~1h access
        # token with nothing to renew and the connection silently 403s. Only when
        # advertised, though: a provider that never claimed the scope may answer
        # invalid_scope, which costs the whole authorization instead of just its
        # refresh token (Google lists openid/email/profile and nothing more).
        if as_metadata.offline_access_supported and "offline_access" not in scope_list:
            scope_list.append("offline_access")
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
