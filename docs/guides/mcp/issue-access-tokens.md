---
title: Issue MCP access tokens
type: guide
summary: Create, scope, rotate, and revoke the API keys that authenticate calls to MCP endpoints and the rest of the API.
prerequisites:
  - /guides/mcp/add-a-hosted-server
related:
  - /guides/mcp/build-a-compound-mcp
  - /guides/mcp/authenticate-with-oauth
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Issue MCP access tokens

Do this when something outside a browser needs to call AgentArea — a harness
connecting to an MCP endpoint, a CI job starting a task, a script. Do not use
these for a downstream MCP server's own credential; that is the server's secret,
covered in [Pass secrets to an MCP
server](/guides/mcp/pass-secrets).

One token type covers the whole API. The same key authenticates
`/v1/mcp/{instance_id}/mcp`, `/client-mcp/{client_id}`, task creation, and A2A.

## Prerequisites

- A browser session or an existing key with access to the workspace. Key
  management is behind normal authentication.
- Somewhere to put the token immediately. The raw value is returned once.

## Steps

### 1. Create a key

```bash
curl -s -X POST "$AGENTAREA_URL/v1/api-keys/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "codex-laptop", "expires_in_days": 90}'
```

```json
{
  "id": "e91b7c04-...",
  "name": "codex-laptop",
  "token_prefix": "aat_9fK2mQx",
  "token": "aat_9fK2mQxR7tB4vLpN8sZaC3dE6gH1jY5uW0oI2rT9nMk",
  "is_active": true,
  "expires_at": "2026-10-27T10:31:02.418907+00:00",
  "access_count": 0,
  "last_accessed_at": null,
  "created_at": "2026-07-29T10:31:02.418907+00:00"
}
```

`token` appears in this 201 response and nowhere else. Only a SHA-256 hash is
stored, so a lost token cannot be recovered — create a new one and revoke the old.

Omit `expires_in_days` for a non-expiring key. Prefer an expiry for anything on a
laptop or in a build.

### 2. Use it

Every endpoint takes the same bearer header. The `aat_` prefix is what routes the
token to API-key validation rather than JWT or OAuth verification.

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp/$INSTANCE_ID/mcp" \
  -H "Authorization: Bearer aat_9fK2mQx..." \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

For a harness, configure the endpoint from the client's `mcp_endpoint_url` and
this token together — see [Combine several MCP servers behind one
endpoint](/guides/mcp/build-a-compound-mcp).

### 3. Audit what exists

```bash
curl -s "$AGENTAREA_URL/v1/api-keys/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '.[] | {name, token_prefix, is_active, expires_at, access_count, last_accessed_at}'
```

`token_prefix` is the first 12 characters, which is how you identify a key
without the secret. `access_count` and `last_accessed_at` tell you whether a key
is still in use — check both before revoking one nobody claims.

### 4. Rotate

There is no rotate endpoint. Rotation is create-then-revoke, in that order:

```bash
NEW=$(curl -s -X POST "$AGENTAREA_URL/v1/api-keys/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "codex-laptop-2026-07", "expires_in_days": 90}' | jq -r '.token')

# deploy $NEW to the consumer, confirm it works, then:
curl -s -o /dev/null -w '%{http_code}\n' \
  -X DELETE "$AGENTAREA_URL/v1/api-keys/$OLD_TOKEN_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

```
204
```

Revocation is immediate — the key is marked inactive and validation refuses it on
the next request. There is no grace period, so revoking before the new key is
deployed is an outage.

## Verify

Confirm the new key authenticates and that the old one no longer does.

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$AGENTAREA_URL/v1/agents/" \
  -H "Authorization: Bearer $NEW"
```

```
200
```

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$AGENTAREA_URL/v1/agents/" \
  -H "Authorization: Bearer $OLD"
```

```
401
```

A 200 then a 401 proves the rotation landed. You can also confirm the key is
being exercised — `access_count` increments on use:

```bash
curl -s "$AGENTAREA_URL/v1/api-keys/$NEW_TOKEN_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '{access_count, last_accessed_at}'
```

## Troubleshooting

**401 on every call with a newly created token.** Check the prefix survived
the copy. A token without the `aat_` prefix is routed to JWT verification, fails
there, and reports the same 401 as a bad key. Shell quoting that drops the
underscore is the usual cause.

**401 after weeks of working.** The key expired. `expires_at` is set at creation
from `expires_in_days` and cannot be extended — `PATCH` is not supported on keys.
Create a replacement.

**A client endpoint answers with "Not authorized for this client".** The key
authenticated but is not authorized for that client bundle, and because
`/client-mcp/{client_id}` speaks MCP the refusal arrives as a JSON-RPC error
rather than an HTTP 403. A workspace key is not automatically permitted to use a
registered client; the principal needs the `use` relation on it, or the token's
subject must be the client itself.

**A key you revoked still appears in the list.** Revocation sets `is_active` to
false rather than deleting the row, so the audit trail survives. Filter on
`is_active` when you want live keys.

**404 revoking a key by its prefix.** `DELETE` takes the key's `id`, not its
`token_prefix`. Look up the id from the list first.

**You need per-endpoint scoping.** These keys carry the workspace access of the
principal that created them; there is no per-endpoint or read-only scope on the
key itself. Constrain what a consumer can reach with governance policy and, for
MCP bundles, by curating the client's member instances — not by scoping the token.

## Related

- [Combine several MCP servers behind one endpoint](/guides/mcp/build-a-compound-mcp)
- [Pass secrets to an MCP server](/guides/mcp/pass-secrets)
- [MCP](/concepts/integration/mcp)
