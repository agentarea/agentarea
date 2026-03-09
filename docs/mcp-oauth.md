---
title: MCP OAuth Integration
description: How AgentArea implements RFC 9728 OAuth 2.0 authorization for MCP servers, enabling Cursor, Claude Desktop, and other MCP clients to authenticate without manual token management.
---

# MCP OAuth Integration

AgentArea exposes each MCP server instance as an OAuth 2.0 protected resource. MCP clients that implement [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728) (Protected Resource Metadata) — including Cursor and Claude Desktop — can discover authorization requirements automatically, register as dynamic clients, and obtain access tokens without any manual configuration.

<Info>
The AgentArea API acts as a single Authorization Server URL for all MCP clients. Hydra handles token issuance internally; clients only ever interact with the AgentArea API endpoints.
</Info>

## How It Works

<CardGroup cols={2}>
  <Card title="RFC 9728 Discovery" icon="magnifying-glass">
    Clients discover the authorization server automatically via `.well-known` metadata endpoints — no hardcoded URLs required.
  </Card>
  <Card title="Dynamic Client Registration" icon="id-card">
    Clients register via RFC 7591 DCR. AgentArea proxies registration to Hydra and injects sane defaults automatically.
  </Card>
  <Card title="Three Auth Types" icon="key">
    MCP instances support `api_key`, `bearer`, and `oauth2` authentication. Credentials are stored encrypted and injected at request time.
  </Card>
  <Card title="OAuth Links" icon="link">
    Generate shareable, OAuth-protected links for MCP instances with workspace-scoped or public access control.
  </Card>
</CardGroup>

---

## RFC 9728 Discovery Flow

This is the exact sequence a client like Cursor or Claude Desktop follows when it encounters an AgentArea MCP endpoint for the first time.

```
Client                          AgentArea API                    Hydra
  │                                   │                            │
  │── GET /mcp/{id} ─────────────────>│                            │
  │<─ 401 WWW-Authenticate: Bearer ───│                            │
  │       resource_metadata="..."     │                            │
  │                                   │                            │
  │── GET /.well-known/               │                            │
  │      oauth-protected-resource ───>│                            │
  │<─ { resource, authorization_      │                            │
  │      servers: [API_BASE_URL] } ───│                            │
  │                                   │                            │
  │── GET /.well-known/               │                            │
  │      oauth-authorization-server ─>│── GET /.well-known/ ──────>│
  │                                   │      openid-configuration  │
  │                                   │<─ OIDC config ─────────────│
  │<─ AS metadata (URLs rewritten     │                            │
  │      to point to API) ────────────│                            │
  │                                   │                            │
  │── POST /oauth2/register ─────────>│── POST /admin/             │
  │   (RFC 7591 DCR)                  │      oauth2/clients ──────>│
  │                                   │<─ client credentials ──────│
  │<─ { client_id, client_secret } ───│                            │
  │                                   │                            │
  │── GET /oauth2/auth ──────────────>│  (browser redirect         │
  │   (browser redirect)              │   to Hydra directly)       │
  │                                            │                   │
  │<──────────────── authorization code ───────│                   │
  │                                   │                            │
  │── POST /oauth2/token ────────────>│── POST /oauth2/token ─────>│
  │                                   │<─ { access_token, ... } ───│
  │<─ { access_token, ... } ──────────│                            │
  │                                   │                            │
  │── GET /mcp/{id} ─────────────────>│                            │
  │   Authorization: Bearer <token>   │                            │
  │<─ 200 OK ─────────────────────────│                            │
```

<Note>
`GET /oauth2/auth` is a browser **redirect**, not a proxy. Hydra must set its own session cookies directly in the browser — proxying this endpoint would break the login flow.
</Note>

### Step-by-Step

<Steps>
  <Step title="Initial 401 Challenge">
    The client makes an unauthenticated request to `/mcp/{instance_id}`. The API responds with `401 Unauthorized` and a `WWW-Authenticate` header pointing to the protected resource metadata URL:

    ```http
    HTTP/1.1 401 Unauthorized
    WWW-Authenticate: Bearer realm="AgentArea",
      resource_metadata="https://api.agentarea.com/.well-known/oauth-protected-resource"
    ```
  </Step>

  <Step title="Protected Resource Metadata">
    The client fetches the resource metadata to discover which authorization servers can issue tokens:

    ```http
    GET /.well-known/oauth-protected-resource
    ```

    ```json
    {
      "resource": "https://api.agentarea.com",
      "authorization_servers": ["https://api.agentarea.com"]
    }
    ```
  </Step>

  <Step title="Authorization Server Metadata">
    The client fetches the AS metadata. AgentArea proxies this from Hydra's OIDC configuration and rewrites all endpoint URLs to point to the AgentArea API:

    ```http
    GET /.well-known/oauth-authorization-server
    ```

    ```json
    {
      "issuer": "https://api.agentarea.com",
      "authorization_endpoint": "https://api.agentarea.com/oauth2/auth",
      "token_endpoint": "https://api.agentarea.com/oauth2/token",
      "registration_endpoint": "https://api.agentarea.com/oauth2/register",
      "jwks_uri": "https://api.agentarea.com/.well-known/jwks.json",
      ...
    }
    ```

    <Tip>
    The JWKS endpoint is also proxied so that token verification works against the AgentArea API URL rather than Hydra's internal address.
    </Tip>
  </Step>

  <Step title="Dynamic Client Registration (RFC 7591)">
    The client registers itself. AgentArea proxies the request to the Hydra admin API and automatically injects:
    - `skip_consent: true` — skips the OAuth consent screen for MCP clients
    - Default audience values scoped to the MCP instance

    ```http
    POST /oauth2/register
    Content-Type: application/json

    {
      "client_name": "Cursor",
      "redirect_uris": ["cursor://oauth/callback"],
      "grant_types": ["authorization_code"],
      "response_types": ["code"]
    }
    ```

    ```json
    {
      "client_id": "abc123",
      "client_secret": "s3cr3t",
      "client_name": "Cursor",
      ...
    }
    ```

    <Warning>
    Hydra v2 does not expose a public DCR endpoint. AgentArea's proxy is the only path for client registration — do not attempt to call Hydra's admin API directly from MCP clients.
    </Warning>
  </Step>

  <Step title="Authorization Code Flow">
    The client redirects the user's browser to `/oauth2/auth`. AgentArea forwards this as a browser redirect (302) to Hydra, which handles login and sets its session cookies. After authentication, Hydra redirects back with an authorization code.
  </Step>

  <Step title="Token Exchange">
    The client exchanges the authorization code for tokens. AgentArea proxies `POST /oauth2/token` to Hydra's public URL:

    ```http
    POST /oauth2/token
    Content-Type: application/x-www-form-urlencoded

    grant_type=authorization_code&code=AUTH_CODE&
    redirect_uri=cursor://oauth/callback&
    client_id=abc123&client_secret=s3cr3t
    ```

    ```json
    {
      "access_token": "eyJ...",
      "token_type": "Bearer",
      "expires_in": 3600,
      "refresh_token": "..."
    }
    ```
  </Step>
</Steps>

---

## Auth Types for MCP Instances

MCP server instances can require authentication themselves — separate from the OAuth flow above. AgentArea supports three auth types that control how credentials are injected into outbound requests to the MCP server.

<Tabs>
  <Tab title="api_key">
    Injects a static key as a custom HTTP header.

    **Config fields:**
    - `header_name` — the header to set (e.g., `X-API-Key`)

    **Credential fields:**
    - `header_value` — the actual key value (stored encrypted)

    ```json
    {
      "auth_type": "api_key",
      "config": {
        "header_name": "X-API-Key"
      }
    }
    ```

    At request time, AgentArea injects:
    ```http
    X-API-Key: <decrypted_header_value>
    ```
  </Tab>

  <Tab title="bearer">
    Injects a static bearer token as the `Authorization` header.

    **Credential fields:**
    - `token` — the bearer token (stored encrypted)

    ```json
    {
      "auth_type": "bearer"
    }
    ```

    At request time, AgentArea injects:
    ```http
    Authorization: Bearer <decrypted_token>
    ```
  </Tab>

  <Tab title="oauth2">
    Manages a full OAuth 2.0 token lifecycle. Supports `client_credentials` and `refresh_token` grant types. Tokens are auto-refreshed 30 seconds before expiry.

    **Config fields:**
    - `client_id` — OAuth client identifier
    - `token_url` — token endpoint URL
    - `grant_type` — `client_credentials` or `refresh_token`
    - `scope` _(optional)_ — requested scopes

    **Credential fields:**
    - `client_secret` — stored encrypted
    - `refresh_token` _(optional)_ — for `refresh_token` grant

    ```json
    {
      "auth_type": "oauth2",
      "config": {
        "client_id": "my-client",
        "token_url": "https://auth.example.com/token",
        "grant_type": "client_credentials",
        "scope": "mcp:read mcp:write"
      }
    }
    ```

    **Token refresh logic:**
    1. If a `refresh_token` is available, attempt `refresh_token` grant first
    2. Fall back to `client_credentials` if refresh fails
    3. New token cached and refreshed automatically 30s before expiry

    <Info>
    All credentials are encrypted at rest via `BaseSecretManager` under the key prefix `mcp_auth_cred`. Plain-text values are never stored in the database.
    </Info>
  </Tab>
</Tabs>

---

## Auth Config API

### Create an Auth Config

```http
POST /api/v1/mcp-auth-configs
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "My Service API Key",
  "auth_type": "api_key",
  "config": {
    "header_name": "X-API-Key"
  },
  "credentials": {
    "header_value": "sk-live-abc123"
  }
}
```

### Link Auth Config to an MCP Instance

```http
PATCH /api/v1/mcp-server-instances/{instance_id}
Authorization: Bearer <token>
Content-Type: application/json

{
  "auth_config_id": "cfg_abc123"
}
```

<Warning>
An auth config cannot be deleted while it is linked to one or more MCP instances. Unlink all instances before deleting the config.
</Warning>

### Get Injected Headers (Internal)

The `get_auth_headers()` method is called internally before each request to an MCP server. It returns the appropriate headers based on auth type — callers do not need to handle this manually.

---

## OAuth Links

OAuth links let you share an MCP instance endpoint that enforces an Authorization Code flow before granting access. This is distinct from the DCR flow above — OAuth links use AgentArea's own identity layer rather than Hydra.

<CardGroup cols={2}>
  <Card title="workspace" icon="building">
    Access restricted to users in the same workspace. Suitable for internal team tooling.
  </Card>
  <Card title="public" icon="globe">
    Any authenticated AgentArea user can access the link. Suitable for published MCP servers.
  </Card>
</CardGroup>

### Flow

<Steps>
  <Step title="Create the Link">
    ```http
    POST /api/v1/mcp-oauth-links
    Authorization: Bearer <token>
    Content-Type: application/json

    {
      "mcp_instance_id": "inst_abc123",
      "access_control": "workspace"
    }
    ```

    Returns a shareable URL with an opaque link token.
  </Step>

  <Step title="Build Authorization URL">
    When a user visits the link, the service builds an authorization URL and redirects them to AgentArea's login/consent flow.
  </Step>

  <Step title="Code Exchange and Session Creation">
    After the user authenticates, the authorization code is exchanged for an identity. A session is created with a 24-hour TTL and an opaque session token is returned.
  </Step>

  <Step title="Authenticated MCP Access">
    The client includes the session token in subsequent requests to the MCP instance. The session is validated on each request.
  </Step>
</Steps>

---

## Hydra Proxy Architecture

```
MCP Client
    │
    ▼
AgentArea API  (:8000)
    ├── /.well-known/oauth-protected-resource    (generated locally)
    ├── /.well-known/oauth-authorization-server  ──proxy──> Hydra /.well-known/openid-configuration
    │                                                       (URLs rewritten to API base)
    ├── /.well-known/jwks.json                   ──proxy──> Hydra public /jwks.json
    ├── POST /oauth2/register                    ──proxy──> Hydra admin /admin/clients
    │                                                       (injects skip_consent, audience)
    ├── GET  /oauth2/auth                        ──302──>   Hydra public /oauth2/auth
    │                                                       (browser redirect, not proxy)
    └── POST /oauth2/token                       ──proxy──> Hydra public /oauth2/token
```

**Why not proxy `/oauth2/auth`?**

Hydra sets session cookies during the login flow. Proxying this endpoint would cause the cookies to be scoped to the AgentArea API domain but sent to Hydra's domain, breaking the session. The browser must talk to Hydra directly for this step.

---

## Security Considerations

| Concern | Mitigation |
|---|---|
| Credential storage | All secrets encrypted via `BaseSecretManager`; never stored in plaintext |
| Token expiry | OAuth2 tokens auto-refreshed 30s before expiry; stale tokens never used |
| Consent bypass | `skip_consent: true` injected only for MCP client registrations |
| Access scope | OAuth links enforce workspace or public access control per-link |
| Session TTL | OAuth link sessions expire after 24 hours; no indefinite sessions |
| DCR exposure | Hydra admin DCR endpoint not exposed publicly; all registration proxied through API |
