---
title: MCP OAuth Integration
description: How AgentArea implements RFC 9728 OAuth 2.0 authorization for MCP servers, enabling Cursor, Claude Desktop, and other MCP clients to authenticate without manual token management.
---

# MCP OAuth Integration

AgentArea exposes each MCP server instance as an OAuth 2.0 protected resource. MCP clients that implement [RFC 9728](https://www.rfc-editor.org/rfc/rfc9728) (Protected Resource Metadata) — including Cursor and Claude Desktop — can discover authorization requirements automatically, register as dynamic clients, and obtain access tokens without any manual configuration.

<Info>
Hydra is the authorization server: its issuer is the one MCP clients discover and the one every token carries. The AgentArea API serves the protected resource metadata and the only client registration endpoint, which Hydra advertises as its own.
</Info>

## How It Works

<CardGroup cols={2}>
  <Card title="RFC 9728 Discovery" icon="magnifying-glass">
    Clients discover the authorization server automatically via `.well-known` metadata endpoints — no hardcoded URLs required.
  </Card>
  <Card title="Dynamic Client Registration" icon="id-card">
    Clients register via RFC 7591 DCR on the AgentArea API, which shapes each registration before creating the client in Hydra.
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
Client                          AgentArea API                    Hydra (issuer)
  │                                   │                            │
  │── GET /mcp/{id} ─────────────────>│                            │
  │<─ 401 WWW-Authenticate: Bearer ───│                            │
  │       resource_metadata="..."     │                            │
  │                                   │                            │
  │── GET /.well-known/               │                            │
  │      oauth-protected-resource ───>│                            │
  │<─ { resource, authorization_      │                            │
  │      servers: [Hydra issuer] } ───│                            │
  │                                   │                            │
  │── GET /.well-known/oauth-authorization-server ────────────────>│
  │<─ AS metadata (registration_endpoint = API /oauth2/register) ──│
  │                                   │                            │
  │── POST /oauth2/register ─────────>│── POST /admin/clients ────>│
  │   (RFC 7591 DCR)                  │<─ client ──────────────────│
  │<─ { client_id, ... } ─────────────│                            │
  │                                   │                            │
  │── GET /oauth2/auth (browser) ─────────────────────────────────>│
  │<─ authorization code ──────────────────────────────────────────│
  │── POST /oauth2/token ─────────────────────────────────────────>│
  │<─ { access_token, ... } ───────────────────────────────────────│
  │                                   │                            │
  │── GET /mcp/{id} ─────────────────>│                            │
  │   Authorization: Bearer <token>   │                            │
  │<─ 200 OK ─────────────────────────│                            │
```

<Note>
The API refuses to describe an authorization server it cannot stand behind: when Hydra's discovery names no issuer, or advertises a `registration_endpoint` other than the API's `/oauth2/register`, both `.well-known` documents answer `502`. Hydra advertises its own registration endpoint unless `webfinger.oidc_discovery.client_registration_url` is set, even with dynamic client registration disabled.
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
      "resource": "https://api.agentarea.com/mcp",
      "authorization_servers": ["https://oauth.agentarea.com"],
      "scopes_supported": ["openid", "offline_access"],
      "bearer_methods_supported": ["header"]
    }
    ```
  </Step>

  <Step title="Authorization Server Metadata">
    The client fetches the metadata from the authorization server it was given. Every endpoint is Hydra's except registration:

    ```http
    GET https://oauth.agentarea.com/.well-known/oauth-authorization-server
    ```

    ```json
    {
      "issuer": "https://oauth.agentarea.com",
      "authorization_endpoint": "https://oauth.agentarea.com/oauth2/auth",
      "token_endpoint": "https://oauth.agentarea.com/oauth2/token",
      "registration_endpoint": "https://api.agentarea.com/oauth2/register",
      "jwks_uri": "https://oauth.agentarea.com/.well-known/jwks.json",
      ...
    }
    ```

    <Tip>
    The API serves the same document unchanged at its own `/.well-known/oauth-authorization-server`, for clients that look for it there.
    </Tip>
  </Step>

  <Step title="Dynamic Client Registration (RFC 7591)">
    The client registers itself on the API, which creates the client through Hydra's admin API after forcing:
    - `skip_consent: false` — every client shows the consent screen
    - `audience` — the API, the audience its tokens are verified against
    - `grant_types` within `authorization_code` and `refresh_token`, scopes within those offered: the configured protocol scopes and `mcp`, never `api`

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
    Hydra's own dynamic client registration stays disabled. The API's `/oauth2/register` is the only path for client registration.
    </Warning>
  </Step>

  <Step title="Authorization Code Flow">
    The client sends the user's browser to Hydra's `authorization_endpoint`. Hydra hands login and consent to the webapp. The consent screen reads the request from the API (`GET /v1/oauth/consent`) and sends the user's decision back to it (`POST /v1/oauth/consent`). The API decides what is granted, then Hydra redirects back with an authorization code. Both consent routes accept a signed-in browser session only.
  </Step>

  <Step title="Token Exchange">
    The client exchanges the authorization code at Hydra's `token_endpoint`:

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
POST /v1/workspaces/{workspace}/mcp-auth-configs
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
PATCH /v1/workspaces/{workspace}/mcp-server-instances/{instance_id}
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
    POST /v1/workspaces/{workspace}/mcp-oauth-links
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

## Client Configuration

With RFC 9728 discovery, MCP clients authenticate automatically -- you only need to point them at the SSE endpoint. No manual token setup required.

<Tabs>
  <Tab title="Cursor">
    Add to your `~/.cursor/mcp.json`:

    ```json
    {
      "mcpServers": {
        "my-agentarea-mcp": {
          "url": "https://your-agentarea.example.com/mcp/<instance-id>/sse"
        }
      }
    }
    ```

    When Cursor connects, it will:
    1. Receive a `401` with `WWW-Authenticate` header
    2. Discover the authorization server via `.well-known` endpoints
    3. Register itself as an OAuth client (DCR)
    4. Open your browser for authorization
    5. Exchange the code for tokens and connect

    <Tip>
    No `Authorization` header or API key needed in the config -- Cursor handles the full OAuth flow automatically via RFC 9728 discovery.
    </Tip>
  </Tab>

  <Tab title="Claude Desktop">
    Add to your `claude_desktop_config.json`:

    ```json
    {
      "mcpServers": {
        "my-agentarea-mcp": {
          "url": "https://your-agentarea.example.com/mcp/<instance-id>/sse"
        }
      }
    }
    ```

    Claude Desktop follows the same RFC 9728 discovery flow as Cursor. The browser-based authorization step opens automatically on first connection.
  </Tab>

  <Tab title="Manual (PAT)">
    If your client does not support RFC 9728, use a [Personal Access Token](/mcp-access-tokens) instead:

    ```json
    {
      "mcpServers": {
        "my-agentarea-mcp": {
          "url": "https://your-agentarea.example.com/mcp/<instance-id>/sse",
          "headers": {
            "Authorization": "Bearer aat_your_token_here"
          }
        }
      }
    }
    ```

    See [MCP Access Tokens](/mcp-access-tokens) for how to create and manage PATs.
  </Tab>
</Tabs>

---

## What a Token Can Do

A token carries what the user granted on the consent screen, and the API enforces it on every request.

| Scope | Granted to | Reaches |
|---|---|---|
| `mcp` | Any client registered through `/oauth2/register` or Hydra's admin API | MCP only (`/mcp`, `/mcp/w/{workspace}`, `/mcp/clients/{id}`), in the workspaces the user ticked on the consent screen |
| `api` | The first-party clients `agentarea-cli` and `agentarea-desktop` | The REST API and MCP, in every workspace the user reaches, including creating API keys and workspaces |

The grant depends on which client asks, not on the scopes it requests: a third-party client that requests `api` is granted `mcp`. The protocol scopes it requested (`openid`, `offline_access`, `offline`, `email`, `profile`) are granted alongside. Under `email` and `profile` the ID token and userinfo carry the user's standard claims, read from their Kratos identity: `email` and `email_verified`; `name`, `given_name`, `family_name`, `preferred_username` and `picture`. The ticked workspaces go into the access token as the `workspace_ids` claim; at least one is required. To change them, the user connects the client again.

- An `mcp` token on the REST API gets `403` with `WWW-Authenticate: Bearer ..., error="insufficient_scope", scope="api"`.
- An `mcp` token on a workspace it was not granted gets `403`.
- A token that carries neither `mcp` nor `api` gets `401`, so the client signs in again.

When the consent grants a scope the client's registration does not allow, the API adds it to the client in Hydra first: Hydra refuses a refresh that asks for a scope the client is not allowed.

The `migrate` role registers the first-party clients in Hydra on every run when `AGENTAREA_AUTH_HYDRA_AUDIENCE` is set. They are public clients with loopback redirects, which Hydra matches on any port.

The protected resource metadata advertises the protocol scopes only. Clients registered before `mcp` existed are not allowed to request it, and Hydra would refuse them at the authorization endpoint before the consent could widen their registration.

---

## Authorization Server Layout

```
MCP Client
    │
    ├──> AgentArea API
    │      ├── /.well-known/oauth-protected-resource[/{path}]   generated; names Hydra's issuer
    │      ├── /.well-known/oauth-authorization-server          Hydra's document, unchanged
    │      └── POST /oauth2/register                            shaped, then Hydra admin /admin/clients
    │
    └──> Hydra (issuer)
           ├── /.well-known/oauth-authorization-server          registration_endpoint = API /oauth2/register
           ├── /oauth2/auth                                      login and consent via the webapp
           ├── /oauth2/token
           └── /.well-known/jwks.json                           the API verifies tokens against it
```

The API also still answers `GET /oauth2/auth` (a redirect to Hydra), `/oauth2/*` and `/.well-known/jwks.json` (forwarded to Hydra) for clients that discovered the earlier metadata, which named the API as every endpoint. Nothing advertises them now.

Serving Hydra's document at the API's own `/.well-known/oauth-authorization-server` departs from RFC 8414, which expects `issuer` to match the URL the document was fetched from. Clients that start from the protected resource metadata (RFC 9728) never read it; it remains for clients that look for it on the API.

Hydra must advertise the API's registration endpoint:

```yaml
webfinger:
  oidc_discovery:
    client_registration_url: https://api.agentarea.com/oauth2/register
```

---

## Security Considerations

| Concern | Mitigation |
|---|---|
| Credential storage | All secrets encrypted via `BaseSecretManager`; never stored in plaintext |
| Token expiry | OAuth2 tokens auto-refreshed 30s before expiry; stale tokens never used |
| Consent bypass | `skip_consent` forced to `false` on every registration; the API decides consent for a signed-in browser session, never for an OAuth token or API key |
| Client impersonation | A client names itself at registration; whatever it is called, it is granted `mcp` in one workspace, never the account |
| Access scope | OAuth links enforce workspace or public access control per-link |
| Session TTL | OAuth link sessions expire after 24 hours; no indefinite sessions |
| DCR exposure | Hydra's own DCR disabled; every registration goes through the API's `/oauth2/register` |
