---
title: Authenticate an MCP server with OAuth
type: guide
summary: Connect a remote MCP instance to a provider that requires OAuth, using discovery and PKCE, so the token is stored and refreshed by the platform.
prerequisites:
  - /guides/mcp/connect-a-remote-server
related:
  - /guides/mcp/pass-secrets
  - /guides/mcp/issue-access-tokens
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Authenticate an MCP server with OAuth

Do this when a remote MCP server rejects a static token and expects an OAuth
authorization-code flow. Use [Pass secrets to an MCP
server](/guides/mcp/pass-secrets) instead when the provider issues a long-lived
API key you can paste.

AgentArea acts as the OAuth client. It discovers the authorization server from
the MCP endpoint, registers itself, runs PKCE, and stores the resulting token as
an auth config linked to the instance. The agent never sees the token.

## Prerequisites

- A `url`-type MCP instance that already exists. OAuth connect resolves the
  remote URL from the instance's parent spec and returns 400 if there is none —
  create the instance first with [Connect a remote MCP
  server](/guides/mcp/connect-a-remote-server).
- The provider's MCP endpoint must publish protected-resource metadata (RFC 9728)
  so the authorization server can be discovered.
- Redis reachable from the API. The in-flight flow state lives there between the
  two requests.
- A browser. The authorization step requires a human at a consent screen.

## Steps

### 1. Start the flow

```bash
curl -s "$AGENTAREA_URL/v1/mcp-oauth/authorize?instance_id=$INSTANCE_ID&return_to=https://app.example.com" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

```json
{
  "authorize_url": "https://provider.example.com/oauth/authorize?response_type=code&client_id=...&code_challenge=...&code_challenge_method=S256&state=..."
}
```

This returns JSON. It does not redirect. Open `authorize_url` in a browser
yourself.

Behind that single call AgentArea discovers the authorization server from the MCP
URL, registers as a client via Dynamic Client Registration where the provider
supports it, generates a PKCE S256 pair, and stores the flow state in Redis keyed
by `state`.

`return_to` is where the browser lands afterwards. It is validated against an
allowed base, so an arbitrary URL is rejected.

### 2. Complete consent in the browser

Open the URL, approve the scopes. The provider redirects to
`GET /v1/mcp-oauth/callback` with `code` and `state`.

The callback is public — it must be, because the provider redirects a browser to
it — and it is protected by the `state` token rather than your API key. It
exchanges the code for tokens, writes an auth config of type `oauth2` holding the
access token, refresh token, scope, and expiry, links it to the instance via
`auth_config_id`, and then redirects the browser to
`{return_to}/mcp-servers/{instance_id}?oauth=success`.

Tool discovery is kicked off in the background at that point, so the tool list
may be a moment behind the redirect.

### 3. Handle a provider without dynamic registration

Some authorization servers do not implement RFC 7591. The flow then needs a
pre-registered OAuth app, supplied to the API as environment variables:

```
MCP_OAUTH_CLIENT_ID=<your registered client id>
MCP_OAUTH_CLIENT_SECRET=<your registered client secret>
```

Register the app with the provider using the callback URL of your deployment.
Without these, `/authorize` returns 502 naming the issuer that refused
registration.

## Verify

Confirm the instance now carries an auth config and that a call through the
governed proxy succeeds with an injected token.

```bash
curl -s "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID" \
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

**400 "Instance has no remote URL configured".** The instance is `docker` or
`command`, not `url`. OAuth connect only applies to remote servers; a managed
workload takes its credential from the environment instead.

**502 "OAuth discovery failed".** The MCP endpoint does not publish
protected-resource metadata, or the authorization server metadata document is
unreachable. Confirm the provider documents OAuth for MCP; if it uses a plain API
key, use [Pass secrets to an MCP
server](/guides/mcp/pass-secrets).

**502 naming the issuer and Dynamic Client Registration.** The authorization
server has no registration endpoint, or registration failed. Register an OAuth
app manually and set `MCP_OAUTH_CLIENT_ID` and `MCP_OAUTH_CLIENT_SECRET`.

**The callback reports an invalid or expired state.** Flow state is held in Redis
with a bounded lifetime and is consumed on first use. A stale browser tab, a
second attempt at the same `authorize_url`, or a Redis restart between the two
steps all produce this. Start again from `/authorize`.

**`return_to` is ignored or rejected.** It is validated against an allowed
frontend base to stop the callback becoming an open redirect. Use your
deployment's configured frontend origin.

**Calls start failing with 401 days later.** The stored refresh token is used to
mint new access tokens, and some providers rotate refresh tokens on each use. If
a refresh fails the connection needs re-authorizing — re-run `/authorize` for the
same instance.

**Two auth configs for one instance.** Each successful flow creates a new auth
config named `mcp-oauth-{first 8 chars of instance id}` and repoints
`auth_config_id`. Older configs are left behind; the instance uses only the one
it points at.

## Related

- [Connect a remote MCP server](/guides/mcp/connect-a-remote-server)
- [Pass secrets to an MCP server](/guides/mcp/pass-secrets)
- [MCP](/concepts/integration/mcp)
