---
title: MCP Access Tokens
description: Personal Access Tokens for Bearer-authenticated MCP proxy access in AgentArea
---

# MCP Access Tokens

<Info>
MCP Access Tokens (PATs) let you authenticate against the AgentArea MCP proxy from any MCP client — Cursor, Claude Desktop, or your own tooling — without exposing your primary credentials.
</Info>

## Overview

AgentArea's MCP proxy sits in front of every managed MCP server instance in your workspace. To connect an external client, you need a **Personal Access Token (PAT)** — a long-lived, revocable credential scoped to your workspace.

<CardGroup cols={3}>
  <Card title="Workspace-Scoped" icon="building">
    A single token grants access to every MCP instance in your workspace
  </Card>
  <Card title="Hash-Only Storage" icon="shield-halved">
    Raw tokens are shown once at creation. Only a SHA-256 hash is ever persisted
  </Card>
  <Card title="Instant Revocation" icon="ban">
    Revoke a token immediately from the API or dashboard — no propagation delay
  </Card>
</CardGroup>

---

## Token Format

Every PAT follows a predictable, identifiable structure:

```
aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234
```

| Part | Value | Description |
|------|-------|-------------|
| **Prefix** | `aat_` | AgentArea Token — identifies token type at a glance |
| **Body** | 43 characters | 32 random bytes encoded as URL-safe base64 |
| **Total length** | 47 characters | Fixed-length, suitable for validation |

<Note>
The first 12 characters after `aat_` (e.g. `aat_AbCdEfGh`) are stored as `token_prefix` and displayed in the dashboard so you can identify tokens without storing the raw value.
</Note>

---

## Lifecycle

```mermaid
sequenceDiagram
    participant User
    participant API
    participant DB

    User->>API: POST /v1/mcp-access-tokens
    API->>API: Generate 32 random bytes
    API->>API: Encode as URL-safe base64 → body
    API->>API: Prepend "aat_" → raw_token
    API->>API: SHA-256(raw_token) → token_hash
    API->>DB: Store {name, token_hash, token_prefix, expires_at}
    API-->>User: Return raw_token (ONCE — never shown again)

    Note over User,DB: Token in use

    User->>API: Any MCP request with Bearer <raw_token>
    API->>API: SHA-256(raw_token) → hash
    API->>DB: Lookup by hash → check is_active + expires_at
    DB-->>API: Valid token record
    API->>DB: Increment access_count, update last_accessed_at
    API-->>User: Proxied MCP response

    Note over User,DB: Revocation

    User->>API: DELETE /v1/mcp-access-tokens/{id}
    API->>DB: SET is_active = false
    API-->>User: 204 No Content
```

---

## API Reference

Base path: `/v1/mcp-access-tokens`

<Tabs>
  <Tab title="Create Token">
    ```http
    POST /v1/mcp-access-tokens
    Content-Type: application/json
    Authorization: Bearer <session-token>

    {
      "name": "cursor-dev-machine",
      "expires_in_days": 90
    }
    ```

    **Response** — the raw token is returned exactly once:

    ```json
    {
      "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "name": "cursor-dev-machine",
      "token": "aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234",
      "token_prefix": "aat_AbCdEfGh",
      "is_active": true,
      "expires_at": "2026-06-09T00:00:00Z",
      "access_count": 0,
      "last_accessed_at": null,
      "created_at": "2026-03-09T12:00:00Z"
    }
    ```

    <Warning>
    Copy the `token` value immediately. It will **never** be shown again. If lost, revoke the token and create a new one.
    </Warning>
  </Tab>

  <Tab title="List Tokens">
    ```http
    GET /v1/mcp-access-tokens
    Authorization: Bearer <session-token>
    ```

    **Response** — raw tokens are never included in list responses:

    ```json
    [
      {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "name": "cursor-dev-machine",
        "token_prefix": "aat_AbCdEfGh",
        "is_active": true,
        "expires_at": "2026-06-09T00:00:00Z",
        "access_count": 142,
        "last_accessed_at": "2026-03-09T11:58:00Z",
        "created_at": "2026-03-09T12:00:00Z"
      }
    ]
    ```
  </Tab>

  <Tab title="Get Token">
    ```http
    GET /v1/mcp-access-tokens/{id}
    Authorization: Bearer <session-token>
    ```

    Returns full token details (excluding raw token and hash).
  </Tab>

  <Tab title="Revoke Token">
    ```http
    DELETE /v1/mcp-access-tokens/{id}
    Authorization: Bearer <session-token>
    ```

    Sets `is_active = false` immediately. Any in-flight requests using the token will be rejected on the next validation check.

    **Response:** `204 No Content`
  </Tab>
</Tabs>

---

## Using Tokens with MCP Clients

<Tabs>
  <Tab title="Cursor">
    Add the following to your Cursor MCP configuration (`~/.cursor/mcp.json` or the project-level `.cursor/mcp.json`):

    ```json
    {
      "mcpServers": {
        "my-agentarea-tool": {
          "url": "https://<your-domain>/mcp/<instance-id>/sse",
          "headers": {
            "Authorization": "Bearer aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234"
          }
        }
      }
    }
    ```

    <Tip>
    Use a project-level config file so each project can reference a different MCP instance while sharing a single workspace token.
    </Tip>
  </Tab>

  <Tab title="Claude Desktop">
    Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or the equivalent path on your OS:

    ```json
    {
      "mcpServers": {
        "my-agentarea-tool": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-fetch"],
          "env": {
            "MCP_SERVER_URL": "https://<your-domain>/mcp/<instance-id>",
            "MCP_AUTH_TOKEN": "aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234"
          }
        }
      }
    }
    ```

    Or, for SSE-native clients that accept raw headers:

    ```json
    {
      "mcpServers": {
        "my-agentarea-tool": {
          "url": "https://<your-domain>/mcp/<instance-id>/sse",
          "headers": {
            "Authorization": "Bearer aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234"
          }
        }
      }
    }
    ```
  </Tab>

  <Tab title="HTTP / curl">
    For direct API testing or custom integrations, pass the token as a standard Bearer header:

    ```bash
    curl -N \
      -H "Authorization: Bearer aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234" \
      -H "Accept: text/event-stream" \
      "https://<your-domain>/mcp/<instance-id>/sse"
    ```

    For JSON-RPC style MCP:

    ```bash
    curl -X POST \
      -H "Authorization: Bearer aat_AbCdEfGhIjKlMnOpQrStUvWxYz012345678901234" \
      -H "Content-Type: application/json" \
      -d '{"jsonrpc":"2.0","method":"tools/list","id":1}' \
      "https://<your-domain>/mcp/<instance-id>"
    ```
  </Tab>
</Tabs>

---

## Creating Your First Token

<Steps>
  <Step title="Open the MCP Servers dashboard">
    Navigate to **MCP Servers** in the AgentArea dashboard and select the instance you want to connect to.
  </Step>

  <Step title="Go to Access Tokens">
    Click the **Access Tokens** tab on the instance detail page, then click **New Token**.
  </Step>

  <Step title="Name and configure the token">
    Give the token a descriptive name that identifies the client or machine it will be used on (e.g. `cursor-laptop`, `ci-pipeline`). Set an expiry appropriate for the use case.

    ```
    Name:        cursor-laptop
    Expires in:  90 days
    ```
  </Step>

  <Step title="Copy the raw token">
    The dashboard displays the full token value exactly once. Copy it now and store it in a password manager or secrets vault.

    <Warning>
    If you navigate away without copying the token, you must revoke it and create a new one. The raw token cannot be recovered.
    </Warning>
  </Step>

  <Step title="Configure your MCP client">
    Paste the token into your client's configuration as shown in the [Using Tokens](#using-tokens-with-mcp-clients) section above.
  </Step>
</Steps>

---

## Token Fields Reference

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique identifier for the token record |
| `name` | string | Human-readable label you provide at creation |
| `token_prefix` | string | First 12 characters (e.g. `aat_AbCdEfGh`) for visual identification |
| `token_hash` | string | SHA-256 hex digest of the raw token — never exposed via API |
| `is_active` | boolean | `false` immediately after revocation |
| `expires_at` | datetime (nullable) | UTC expiry; `null` means no expiry |
| `access_count` | integer | Total number of validated requests |
| `last_accessed_at` | datetime (nullable) | Timestamp of the most recent validated request |

---

## Security Best Practices

<CardGroup cols={2}>
  <Card title="One token per client" icon="key">
    Issue a separate token for each machine or integration. This lets you revoke access for a specific client without affecting others.
  </Card>
  <Card title="Set expiry dates" icon="calendar-xmark">
    Prefer short-lived tokens (30-90 days) over non-expiring ones. Rotate tokens regularly, especially after team member changes.
  </Card>
  <Card title="Store in secrets managers" icon="vault">
    Never commit tokens to source control. Use environment variables, a password manager, or a secrets manager (Infisical, AWS Secrets Manager, HashiCorp Vault).
  </Card>
  <Card title="Monitor access counts" icon="chart-line">
    Unexpected spikes in `access_count` or activity from an unexpected `last_accessed_at` timestamp may indicate a compromised token. Revoke immediately if suspicious.
  </Card>
  <Card title="Revoke unused tokens" icon="trash">
    Periodically audit your token list and revoke any tokens that are no longer in active use or belong to departed team members.
  </Card>
  <Card title="Prefer short names" icon="tag">
    Use names like `cursor-alice-laptop` or `ci-github-actions` so you can identify the token's origin at a glance when auditing.
  </Card>
</CardGroup>

<Warning>
A PAT grants access to **all MCP instances in its workspace**. Treat it with the same care as a root API key. If a token is compromised, revoke it immediately via `DELETE /v1/mcp-access-tokens/{id}` — revocation takes effect instantly.
</Warning>

---

## Validation Logic

When the MCP proxy receives a request, it validates the Bearer token through the following checks in order:

1. **Format check** — token must start with `aat_`
2. **Hash lookup** — SHA-256 of the token is computed and matched against stored hashes
3. **Active check** — `is_active` must be `true`
4. **Expiry check** — `expires_at` must be `null` or in the future
5. **Access recording** — `access_count` incremented and `last_accessed_at` updated

Any failed check returns `401 Unauthorized`. The raw token is never logged.

---

## Related

<CardGroup cols={2}>
  <Card title="MCP Integration" icon="plug" href="/mcp-integration">
    Learn how AgentArea manages MCP server instances
  </Card>
  <Card title="Security" icon="shield-halved" href="/security">
    Workspace scoping, authentication, and secrets management
  </Card>
</CardGroup>
