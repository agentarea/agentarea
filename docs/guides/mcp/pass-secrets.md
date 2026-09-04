---
title: Pass secrets to an MCP server
type: guide
summary: Declare which inputs are credentials with env_schema, supply their values on the instance, and confirm they were moved into the secret manager and masked.
prerequisites:
  - /guides/mcp/add-a-hosted-server
related:
  - /guides/mcp/connect-a-remote-server
  - /guides/mcp/authenticate-with-oauth
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Pass secrets to an MCP server

Do this when an MCP server needs an API key, token, or password — as an
environment variable for a managed workload, or as an HTTP header for a remote
one. Use [Authenticate an MCP server with
OAuth](/guides/mcp/authenticate-with-oauth) when the provider requires an
authorization-code flow rather than a static credential.

A value you send here does not stay in the instance record. Names declared secret
are moved into the secret manager on write and masked on every read.

## Prerequisites

- An API key for the workspace.
- The names the server expects, and whether each is a credential or plain
  configuration.

## How sensitivity is decided

The spec's `env_schema` decides, and nothing else. An entry with
`"isSecret": true` is a credential; an entry without it is plain configuration
that stays readable in `json_spec`.

Names are never inspected to guess sensitivity. When you create an instance
without an explicit spec, AgentArea auto-creates one and marks **every**
environment variable and header as secret, because with no declared schema the
safe default is to treat everything as a credential. Declare the schema
explicitly if you want some values to stay readable.

## Steps

### 1. Declare the schema on the spec

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-servers/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "GitHub",
    "description": "GitHub tools.",
    "remote_url": "https://api.githubcopilot.com/mcp/",
    "env_schema": [
      {"name": "Authorization", "description": "Bearer <PAT>", "isSecret": true},
      {"name": "X-Org", "description": "Organisation slug", "isSecret": false}
    ]
  }'
```

### 2. Supply the values on the instance

For a remote server, credentials go in `headers`:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"GitHub\",
    \"server_spec_id\": \"$SPEC_ID\",
    \"json_spec\": {
      \"type\": \"url\",
      \"endpoint_url\": \"https://api.githubcopilot.com/mcp/\",
      \"headers\": {\"Authorization\": \"Bearer ghp_...\", \"X-Org\": \"acme\"}
    }
  }"
```

For a managed workload they go in `environment`:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Postgres\",
    \"server_spec_id\": \"$SPEC_ID\",
    \"json_spec\": {
      \"type\": \"docker\",
      \"image\": \"mcp/postgres:latest\",
      \"environment\": {\"DATABASE_URL\": \"postgres://user:pw@host/db\"}
    }
  }"
```

On write, each value whose name is marked secret is removed from `json_spec`,
stored in the secret manager under a key derived from the instance id and the
variable name, and its name appended to `json_spec.env_vars`. That list is the
record of which names are secret-backed.

### 3. Rotate a credential

Send the new value the same way with `PATCH`:

```bash
curl -s -X PATCH "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"json_spec": {"type": "url", "endpoint_url": "https://api.githubcopilot.com/mcp/", "headers": {"Authorization": "Bearer ghp_NEW"}}}'
```

Then re-verify, because the stored tool list was discovered with the old
credential:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID/verify" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.verification.status'
```

Do not send back the masked placeholder. A `PATCH` carrying `******` as a value
is a no-op for that field by design, so an edit-then-save round trip in a UI
cannot overwrite a real secret with asterisks.

## Verify

Two checks. First, that the names are registered as secret-backed and the values
are masked:

```bash
curl -s "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '{env_vars: .json_spec.env_vars, headers: .json_spec.headers}'
```

```json
{
  "env_vars": ["Authorization"],
  "headers": {
    "Authorization": "******",
    "X-Org": "acme"
  }
}
```

`Authorization` is masked and listed in `env_vars`; `X-Org` stays readable
because the schema marked it non-secret. If a credential appears in plaintext
here, its `env_schema` entry is missing or `isSecret` is false.

Second, that a value is actually present in the secret manager:

```bash
curl -s "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID/environment" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq
```

```json
{
  "instance_id": "5a91c2d0-...",
  "env_vars": ["Authorization"],
  "message": "Instance has 1 environment variables configured"
}
```

This endpoint returns names only, never values. A name declared secret but absent
from this list has no stored value.

## Troubleshooting

**The credential is readable in `json_spec`.** Its name is not marked
`isSecret: true` in the spec's `env_schema`, so it was treated as plain
configuration. Update the spec, then re-send the value on the instance — fixing
the schema alone does not move an already-stored plaintext value.

**Every value came back masked when you only wanted one secret.** The instance
was created without an explicit spec, so a schema was derived with everything
marked secret. Create the spec with an explicit `env_schema` and point a new
instance at it.

**Verification fails with 401 right after a rotation.** The new value was
supplied under a name the server does not expect, or the placeholder was sent
instead of a real value. Confirm the name appears in
`GET /v1/mcp-server-instances/{instance_id}/environment`, then re-verify.

**A managed container starts and immediately dies.** A required environment
variable is missing. Because secret values are stripped from `json_spec`, an
inspection of the instance cannot tell you whether a value exists — use the
`/environment` endpoint, which lists the names that do.

**Tools still work after you revoked the credential upstream.** The tool list is
a snapshot from the last successful verification and nothing re-verifies a
healthy instance on a schedule. Revoking at the provider does not update
AgentArea's view until the next verification or a live call fails.

## Related

- [Add a hosted MCP server](/guides/mcp/add-a-hosted-server)
- [Authenticate an MCP server with OAuth](/guides/mcp/authenticate-with-oauth)
- [MCP](/concepts/integration/mcp)
