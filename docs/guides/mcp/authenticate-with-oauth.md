---
title: Authenticate an MCP server with OAuth
type: guide
description: "Connect a remote MCP instance to a provider that requires OAuth, using discovery and PKCE, so the token is stored and refreshed by the platform."
prerequisites:
  - /guides/mcp/connect-a-remote-server
related:
  - /guides/mcp/pass-secrets
  - /guides/mcp/issue-access-tokens
  - /concepts/integration/mcp
last_updated: 2026-09-22
---

Do this when a remote MCP server rejects a static token and expects an OAuth
authorization-code flow. Use [Pass secrets to an MCP
server](/guides/mcp/pass-secrets) instead when the provider issues a long-lived
API key you can paste.

AgentArea acts as the OAuth client. It discovers the authorization server from
the MCP endpoint, registers itself where the provider allows it, runs PKCE, and
stores the resulting token as an auth config linked to the instance. The agent
never sees the token.

Providers split into two cases, and which one you are in decides whether there
is anything to prepare: those that implement Dynamic Client Registration
(RFC 7591) let AgentArea register itself, and those that do not — Google and
GitHub among them — require an OAuth app you register with the provider and
supply per connection. Ask the preflight endpoint rather than guessing.

## Prerequisites

<Info>
- A `url`-type MCP instance that already exists. OAuth connect resolves the
  remote URL from the instance's parent spec and returns 400 if there is none —
  create the instance first with [Connect a remote MCP
  server](/guides/mcp/connect-a-remote-server).
- The provider's MCP endpoint must publish protected-resource metadata (RFC 9728)
  so the authorization server can be discovered.
- Redis reachable from the API. The in-flight flow state lives there between the
  two requests.
- A browser. The authorization step requires a human at a consent screen.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Ask what the provider needs">
    ```bash
    curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-oauth/preflight?instance_id=$INSTANCE_ID" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```

    ```json
    {
      "instance_id": "76216436-01e9-4ebc-a8d5-9023ed773cce",
      "status": "oauth_app_required",
      "connected": false,
      "detail": "https://accounts.google.com does not support Dynamic Client Registration (RFC 7591), so AgentArea cannot register itself. Register an OAuth app with this provider and connect with its client ID and secret.",
      "issuer": "https://accounts.google.com",
      "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
      "scopes": ["https://www.googleapis.com/auth/gmail.modify"]
    }
    ```

    `status` decides the next step:

    | `status` | What it means | Next |
    |---|---|---|
    | `ready` | The provider implements RFC 7591 | Authorize with no credentials |
    | `oauth_app_required` | No dynamic registration; `detail` names the issuer | Register an app with the provider, then authorize with `credential_mode: custom` |
    | `unsupported` | No OAuth discovery here; `detail` says what failed | Use [Pass secrets to an MCP server](/guides/mcp/pass-secrets), or nothing if the server needs no token |

    Pass `server_id` instead of `instance_id` to ask about a catalog spec before
    any connection exists; `connected` is then always `false`.

    Every outcome is a 200 — the endpoint answers a question about capability
    rather than failing. It runs live discovery against the MCP URL on each call,
    so expect a round trip to the provider.
  </Step>

  <Step title="Start the flow">
    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-oauth/authorize" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"instance_id\": \"$INSTANCE_ID\", \"return_to\": \"https://app.example.com\"}"
    ```

    ```json
    {
      "authorize_url": "https://provider.example.com/oauth/authorize?response_type=code&client_id=...&code_challenge=...&code_challenge_method=S256&state=..."
    }
    ```

    This returns JSON. It does not redirect. Open `authorize_url` in a browser
    yourself.

    Behind that single call AgentArea discovers the authorization server from the MCP
    URL, registers as a client via Dynamic Client Registration, generates a PKCE S256
    pair, persists the client credentials on an auth config, and stores the flow state
    in Redis keyed by `state`. The state holds a reference to those credentials, never
    a copy of the client secret.

    The requested scopes come from the resource's own metadata (RFC 9728) where it
    publishes them, since that is the only place a provider states what the MCP
    endpoint itself accepts. `offline_access` is added only when the authorization
    server advertises it — asking a provider for a scope it never claimed risks
    `invalid_scope` on the consent screen, which costs the whole authorization
    rather than just its refresh token. Google ignores `offline_access` altogether and
    issues a refresh token only for `access_type=offline` on a fresh consent, so
    its authorize URL carries `access_type=offline` and `prompt=consent` instead.

    `return_to` is where the browser lands afterwards. It is validated against an
    allowed base, so an arbitrary URL is rejected.
  </Step>

  <Step title="Complete consent in the browser">
    Open the URL, approve the scopes. The provider redirects to
    `GET /v1/mcp-oauth/callback` with `code` and `state`.

    The callback is public — it must be, because the provider redirects a browser to
    it — and it is protected by the `state` token rather than your API key. It
    exchanges the code for tokens, updates the auth config created in the previous
    step with the access token, refresh token, scope, and expiry, links it to the
    instance via `auth_config_id`, and then redirects the browser to
    `{return_to}/connections/{instance_id}?oauth=success`.

    Tool discovery is kicked off in the background at that point, so the tool list
    may be a moment behind the redirect.
  </Step>

  <Step title="Connect a provider without dynamic registration">
    When preflight returned `oauth_app_required`, register an OAuth app with the
    provider yourself, using your deployment's callback URL
    (`$AGENTAREA_URL/v1/mcp-oauth/callback`) as its redirect URI. Then pass its
    credentials with the authorize call:

    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-oauth/authorize" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"instance_id\": \"$INSTANCE_ID\", \"credential_mode\": \"custom\", \"client_id\": \"$CLIENT_ID\", \"client_secret\": \"$CLIENT_SECRET\"}"
    ```

    The credentials belong to the connection, not to the deployment: each workspace
    authorizes through its own app, and the client secret is stored encrypted under
    the connection's auth config.

    Either credential can instead reference an existing workspace secret, which is
    what to use when you rotate the app without re-authorizing every connection:

    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-oauth/authorize" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"instance_id\": \"$INSTANCE_ID\", \"credential_mode\": \"custom\", \"client_id_secret_id\": \"$CLIENT_ID_SECRET_ID\", \"client_secret_secret_id\": \"$CLIENT_SECRET_SECRET_ID\"}"
    ```

    Exactly one source per credential. Sending both a value and a secret id for the
    same credential, or neither, is rejected with 422 rather than one silently
    winning. Referenced secrets must be user-owned workspace secrets — a secret
    already owned by another entity is refused.
  </Step>
</Steps>

## Verify

Confirm the instance now carries an auth config and that a call through the
governed proxy succeeds with an injected token.

```bash
curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-server-instances/$INSTANCE_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '{auth_config_id, status: .verification.status, tools: (.tools | length)}'
```

```json
{
  "auth_config_id": "7c2e91ab-...",
  "status": "succeeded",
  "tools": 9
}
```

Then exercise the proxy, which is what injects the token:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp/$INSTANCE_ID/mcp" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

A JSON-RPC result rather than a 401 proves the stored token is being used. Your
own `Authorization` header is stripped before the request goes upstream, so this
only succeeds if the OAuth credential was stored correctly.

## Troubleshooting

<AccordionGroup>
  <Accordion title='400 "Instance has no remote URL configured"'>
    The instance is `docker` or `command` , not `url` . OAuth connect only
    applies to remote servers; a managed workload takes its credential from the
    environment instead.
  </Accordion>
  <Accordion title='502 "OAuth discovery failed"'>
    The MCP endpoint does not publish protected-resource metadata, or the
    authorization server metadata document is unreachable. Confirm the provider
    documents OAuth for MCP; if it uses a plain API key, use
    [Pass secrets to an MCP server](/guides/mcp/pass-secrets) .
  </Accordion>
  <Accordion title='422 with code "oauth_app_required"'>
    The authorization server has no registration endpoint, or registration
    failed, so there is no client for AgentArea to authorize as. The response
    names the issuer in `detail.issuer` . Register an OAuth app with that
    provider and retry with `credential_mode: custom` .
  </Accordion>
  <Accordion title="A verified connection still cannot call tools">
    A remote server that lists its tools without a token verifies as reachable
    and stores its tool list while nobody is authorized; the tool calls are what
    401. Check `auth_config_id` on the instance — `null` means no token is
    stored, regardless of `verification.status` .
  </Accordion>
  <Accordion title="The callback reports an invalid or expired state">
    Flow state is held in Redis with a bounded lifetime and is consumed on first
    use. A stale browser tab, a second attempt at the same `authorize_url` , or
    a Redis restart between the two steps all produce this. Start again from
    `/authorize` .
  </Accordion>
  <Accordion title="`return_to` is ignored or rejected">
    It is validated against an allowed frontend base to stop the callback
    becoming an open redirect. Use your deployment's configured frontend origin.
  </Accordion>
  <Accordion title="Calls start failing with 401 days later">
    The stored refresh token is used to mint new access tokens, and some
    providers rotate refresh tokens on each use. If a refresh fails the
    connection needs re-authorizing — re-run `/authorize` for the same instance.
  </Accordion>
  <Accordion title="Two auth configs for one instance">
    Each successful flow creates a new auth config named
    `mcp-oauth-{first 8 chars of instance id}` and repoints `auth_config_id` .
    Older configs are left behind; the instance uses only the one it points at.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Connect a remote MCP server" icon="plug" href="/guides/mcp/connect-a-remote-server">
    Point AgentArea at an MCP server somebody else operates, test the endpoint
    before saving it
  </Card>
  <Card title="Pass secrets to an MCP server" icon="plug" href="/guides/mcp/pass-secrets">
    Declare which inputs are credentials with env_schema, supply their values on
    the instance
  </Card>
  <Card title="MCP" icon="plug" href="/concepts/integration/mcp">
    What the Model Context Protocol gives an agent, and how AgentArea hosts MCP
    servers
  </Card>
</Columns>
