"""RFC 9728 OAuth Protected Resource Metadata endpoint + AS discovery proxy.

Discovery chain that Cursor / Claude Desktop follow:

    1. GET /mcp/{id}  →  401 + WWW-Authenticate: Bearer resource_metadata="…"
    2. GET /.well-known/oauth-protected-resource
           →  {"resource": "<API>/mcp", "authorization_servers": ["<Hydra issuer>"]}
    3. GET <Hydra issuer>/.well-known/oauth-authorization-server
           →  Hydra metadata: authorization_endpoint, token_endpoint, registration_endpoint, …
    4. POST <registration_endpoint>  →  our /oauth2/register proxy (Hydra has no public DCR)
    5. GET  <authorization_endpoint> / POST <token_endpoint>  →  Hydra directly

We advertise Hydra as the authorization server because Hydra issues the tokens:
its issuer is what lands in the token's ``iss``, and clients that validate it
reject tokens that disagree with the metadata they discovered. Hydra points step
4 back at our proxy via ``webfinger.oidc_discovery.client_registration_url``.

When Hydra does not advertise a registration endpoint (DCR unconfigured), we
keep advertising ourselves and serve the AS metadata + oauth2/* proxy below, so
dynamic client registration still works on deployments that rely on the shim.
"""

import re

import httpx
from agentarea_common.config import get_settings
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

oauth_as_router = APIRouter(tags=["oauth-as"])

# Conservative allowlist for the proxied /oauth2/{path} subpath. The host is
# fixed to HYDRA_PUBLIC_URL, so the caller can only influence the path/query;
# restrict the path to OAuth2-style identifiers and forbid parent traversal so a
# request cannot escape /oauth2/ on the Hydra host (partial-SSRF hardening).
_SAFE_OAUTH2_SUBPATH = re.compile(r"^[A-Za-z0-9._~/-]+$")


def _is_safe_oauth2_subpath(path: str) -> bool:
    if not path or not _SAFE_OAUTH2_SUBPATH.match(path):
        return False
    return ".." not in path.split("/")


def _hydra_public_url() -> str:
    return get_settings().mcp.HYDRA_PUBLIC_URL.rstrip("/")


# Hydra's discovery document, fetched once and reused.
_hydra_discovery_cache: dict | None = None


async def _hydra_discovery() -> dict | None:
    """Hydra's OIDC discovery document, or None when it is unreachable."""
    global _hydra_discovery_cache
    if _hydra_discovery_cache is not None:
        return _hydra_discovery_cache

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(5)) as client:
            resp = await client.get(f"{_hydra_public_url()}/.well-known/openid-configuration")
            resp.raise_for_status()
            doc = resp.json()
    except Exception:
        return None

    if isinstance(doc, dict):
        _hydra_discovery_cache = doc
    return _hydra_discovery_cache


# The MCP endpoints this API protects. Each is its own protected resource with
# its own canonical URI, and RFC 9728 §3.1 derives the metadata URL from that
# URI by inserting the well-known segment before the path — so the document has
# to be reachable at the path-suffixed location as well as at the root one.
_PROTECTED_RESOURCE_PATHS = ("mcp", "client-mcp")


async def _protected_resource_metadata(resource_path: str) -> JSONResponse:
    """RFC 9728: advertise the authorization server that actually issues tokens."""
    settings = get_settings()
    api_base = settings.app.API_BASE_URL.rstrip("/")

    # Hydra mints the tokens, so Hydra — not this API — is the authorization
    # server identity. Its issuer ends up in the token's `iss`, and clients that
    # validate the issuer (RFC 9207, required by the MCP auth spec) reject a
    # token whose `iss` disagrees with the metadata they discovered. Pointing at
    # ourselves therefore only works for clients that skip that check.
    #
    # Only delegate when Hydra also advertises a registration endpoint: MCP
    # clients need dynamic client registration, and Hydra exposes it in its own
    # discovery document only when webfinger.oidc_discovery.client_registration_url
    # is configured (it has no public DCR of its own — see the proxy below).
    # Without it, stay on the local AS shim so DCR keeps working.
    doc = await _hydra_discovery()
    issuer = (doc or {}).get("issuer", "").rstrip("/")
    as_url = issuer if issuer and (doc or {}).get("registration_endpoint") else api_base

    return JSONResponse(
        content={
            # MCP spec: canonical URI of the MCP server endpoint, not the API root.
            "resource": f"{api_base}/{resource_path}",
            "authorization_servers": [as_url],
            "bearer_methods_supported": ["header"],
        }
    )


@oauth_as_router.get("/.well-known/oauth-protected-resource")
async def oauth_protected_resource_metadata() -> JSONResponse:
    """The root location, which is what our own ``WWW-Authenticate`` points at."""
    return await _protected_resource_metadata("mcp")


@oauth_as_router.get("/.well-known/oauth-protected-resource/{resource_path}")
async def oauth_protected_resource_metadata_by_path(resource_path: str) -> JSONResponse:
    """The RFC 9728 §3.1 location, which strict clients derive from the resource URI.

    Restricted to the endpoints we actually protect: a catch-all would answer
    for any path and claim this API protects resources it does not serve.
    """
    if resource_path not in _PROTECTED_RESOURCE_PATHS:
        raise HTTPException(status_code=404, detail="Unknown protected resource")
    return await _protected_resource_metadata(resource_path)


@oauth_as_router.get("/.well-known/oauth-authorization-server")
async def oauth_authorization_server_metadata() -> JSONResponse:
    """RFC 8414: serve Hydra's OIDC config at the standard AS discovery path.

    Hydra v2 only serves /.well-known/openid-configuration; we bridge the gap
    so MCP clients (Cursor) that look for /.well-known/oauth-authorization-server
    still get the Hydra endpoints, rewritten to point to our proxy paths.
    """
    settings = get_settings()
    api_base = settings.app.API_BASE_URL.rstrip("/")
    hydra_url = _hydra_public_url()

    async with httpx.AsyncClient(timeout=httpx.Timeout(5)) as client:
        resp = await client.get(f"{hydra_url}/.well-known/openid-configuration")
        resp.raise_for_status()
        hydra_meta = resp.json()

    # Hydra uses its public issuer URL in metadata (e.g. http://localhost:4444),
    # not its internal Docker hostname. Rewrite from the issuer URL, not the
    # internal URL, so auth/token/revoke endpoints all point to our API.
    hydra_issuer = hydra_meta.get("issuer", hydra_url).rstrip("/")

    def _rewrite(url: str | None) -> str | None:
        if not url:
            return url
        for prefix in (hydra_issuer, hydra_url):
            if url.startswith(prefix):
                return url.replace(prefix, api_base, 1)
        return url

    return JSONResponse(
        content={
            "issuer": api_base,
            "authorization_endpoint": _rewrite(hydra_meta.get("authorization_endpoint")),
            "token_endpoint": _rewrite(hydra_meta.get("token_endpoint")),
            "registration_endpoint": f"{api_base}/oauth2/register",
            "jwks_uri": _rewrite(hydra_meta.get("jwks_uri")),
            "response_types_supported": hydra_meta.get("response_types_supported", ["code"]),
            "grant_types_supported": hydra_meta.get(
                "grant_types_supported", ["authorization_code"]
            ),
            "code_challenge_methods_supported": hydra_meta.get(
                "code_challenge_methods_supported", ["S256"]
            ),
            "token_endpoint_auth_methods_supported": hydra_meta.get(
                "token_endpoint_auth_methods_supported", ["none"]
            ),
            "revocation_endpoint": _rewrite(hydra_meta.get("revocation_endpoint")),
        }
    )


# ---------------------------------------------------------------------------
# Hydra OAuth2 proxy — forward oauth2/* and related paths to Hydra
# This lets Cursor use our API_BASE_URL as the single AS URL for all ops.
# ---------------------------------------------------------------------------


@oauth_as_router.get("/oauth2/auth")
async def hydra_auth_redirect(request: Request) -> Response:
    """Redirect the browser to Hydra's actual /oauth2/auth endpoint.

    Unlike the other OAuth2 endpoints which we proxy server-side, the auth
    endpoint MUST be a browser redirect because Hydra sets session cookies
    during the authorization flow.  If we proxy it, the cookies land on our
    domain (localhost:8000) but Hydra's subsequent redirects go to its own
    domain (localhost:4444), losing the cookies and breaking the flow.
    """
    from fastapi.responses import RedirectResponse

    settings = get_settings()
    hydra_browser = settings.mcp.HYDRA_BROWSER_URL.rstrip("/")
    target = f"{hydra_browser}/oauth2/auth"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(url=target, status_code=302)


@oauth_as_router.post("/oauth2/register")
async def hydra_dcr_proxy(request: Request) -> Response:
    """Dynamic Client Registration (RFC 7591) — proxy to Hydra admin API.

    Hydra v2 doesn't expose public DCR; we proxy POST /oauth2/register to
    Hydra's admin endpoint so Cursor / Claude Desktop can self-register.

    We inject server-side defaults:
      - skip_consent: true — MCP clients accessing their own workspace don't need consent
      - audience: [API_BASE_URL] — ensures issued JWTs have the correct audience for validation
    """
    import json as _json

    settings = get_settings()
    admin_url = settings.mcp.HYDRA_ADMIN_URL.rstrip("/")
    api_base = settings.app.API_BASE_URL.rstrip("/")

    try:
        client_data = _json.loads(await request.body())
    except Exception:
        client_data = {}

    # Inject server-side defaults for MCP clients.
    # Hydra requires client_uri to be a valid URL and contacts to be an array;
    # MCP clients (Cursor, Claude Desktop) often omit these in their DCR payload.
    client_data.setdefault("skip_consent", True)
    client_data.setdefault("audience", [api_base])
    client_data.setdefault("client_uri", api_base)
    if not client_data.get("contacts"):
        client_data["contacts"] = []

    async with httpx.AsyncClient(timeout=httpx.Timeout(15)) as client:
        upstream = await client.post(
            f"{admin_url}/admin/clients",
            content=_json.dumps(client_data).encode(),
            headers={"Content-Type": "application/json"},
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers={"Content-Type": "application/json"},
    )


@oauth_as_router.get(
    "/oauth2/{path:path}",
    operation_id="hydra_oauth2_proxy_oauth2__path__get",
)
@oauth_as_router.post(
    "/oauth2/{path:path}",
    operation_id="hydra_oauth2_proxy_oauth2__path__post",
)
@oauth_as_router.put(
    "/oauth2/{path:path}",
    operation_id="hydra_oauth2_proxy_oauth2__path__put",
)
@oauth_as_router.delete(
    "/oauth2/{path:path}",
    operation_id="hydra_oauth2_proxy_oauth2__path__delete",
)
@oauth_as_router.patch(
    "/oauth2/{path:path}",
    operation_id="hydra_oauth2_proxy_oauth2__path__patch",
)
async def hydra_oauth2_proxy(path: str, request: Request) -> Response:
    """Proxy all /oauth2/* requests through to Hydra (excluding /register handled above)."""
    if not _is_safe_oauth2_subpath(path):
        return JSONResponse(
            content={"error": "invalid_request", "error_description": "invalid oauth2 path"},
            status_code=400,
        )

    hydra_url = _hydra_public_url()
    target = f"{hydra_url}/oauth2/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
        upstream = await client.request(
            method=request.method,
            url=target,
            content=await request.body(),
            headers=forward_headers,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
    )


@oauth_as_router.get("/.well-known/jwks.json")
async def hydra_jwks_proxy(request: Request) -> Response:
    """Proxy JWKS so token verification works against our API URL."""
    hydra_url = _hydra_public_url()
    async with httpx.AsyncClient(timeout=httpx.Timeout(10)) as client:
        resp = await client.get(f"{hydra_url}/.well-known/jwks.json")
    return Response(content=resp.content, status_code=resp.status_code, headers=dict(resp.headers))
