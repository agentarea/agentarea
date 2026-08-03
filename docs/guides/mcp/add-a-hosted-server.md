---
title: Add a hosted MCP server
type: guide
summary: Run an MCP server as a managed workload — a container image or a published npm/PyPI package — and confirm it came up by checking its verification.
prerequisites:
  - /concepts/integration/mcp
related:
  - /guides/mcp/connect-a-remote-server
  - /guides/mcp/pass-secrets
  - /guides/mcp/build-a-compound-mcp
last_updated: 2026-07-29
---

# Add a hosted MCP server

Do this when the MCP server is code that AgentArea should run — a published
container image, or an npm or PyPI package launched with `npx` or `uvx`. Use
[Connect a remote MCP server](/guides/mcp/connect-a-remote-server) instead when
somebody else already operates the server at a URL.

Hosting means AgentArea provisions and supervises the workload, and the agent
never reaches the server directly.

## Prerequisites

- An API key for the workspace.
- The image reference, or the package name and its launch command.
- The MCP manager reachable from the API. Managed instances cannot be
  provisioned without it.

## Choose a creation path

| Option | Pick it when |
|---|---|
| `POST /v1/mcp-server-instances/with-spec` | Default. Creates the reusable spec and one configured instance in a single call. |
| `POST /v1/mcp-servers/` then `POST /v1/mcp-server-instances/` | You want one spec reused by several instances with different configuration. |

The spec describes *what the server is* — image, command, and the `env_schema`
declaring the inputs it needs. The instance is *one configured copy* of it.

## Steps

### Option A — container image, one call

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/with-spec" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server": {
      "name": "Filesystem",
      "description": "Read-only filesystem access for the agent.",
      "docker_image_url": "mcp/filesystem:latest",
      "version": "1.0.0",
      "tags": ["files"],
      "env_schema": [
        {"name": "ALLOWED_DIRECTORIES", "description": "Comma-separated roots", "isSecret": false}
      ]
    },
    "instance": {
      "name": "Filesystem (shared)",
      "json_spec": {
        "type": "docker",
        "image": "mcp/filesystem:latest",
        "environment": {"ALLOWED_DIRECTORIES": "/data"}
      }
    }
  }'
```

The response is the instance, including its `verification` block. A managed
instance returns **202**, not 201: verification runs in the background, so the
`verification.status` in this response is the starting state, not the outcome.
Remote (`url`) instances verify synchronously and return 201.

### Option B — published package

Use `type: "command"`. The package is wrapped in the `agentarea/mcp-bridge`
container, which listens on port 8080; you do not set a port.

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/with-spec" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "server": {
      "name": "Sequential Thinking",
      "description": "Structured reasoning tools.",
      "cmd": ["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"],
      "version": "1.0.0",
      "tags": ["reasoning"]
    },
    "instance": {
      "name": "Sequential Thinking",
      "json_spec": {
        "type": "command",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]
      }
    }
  }'
```

Only five keys in `json_spec` are treated as transport: `type`, `endpoint_url`,
`image`, `command`, `args`. Everything else — `environment`, `headers`, `port` —
is instance configuration.

### Option C — separate spec and instances

Create the spec once:

```bash
SPEC_ID=$(curl -s -X POST "$AGENTAREA_URL/v1/mcp-servers/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Filesystem",
    "description": "Read-only filesystem access.",
    "docker_image_url": "mcp/filesystem:latest",
    "env_schema": [{"name": "ALLOWED_DIRECTORIES", "isSecret": false}]
  }' | jq -r '.id')
```

Then create each instance against it:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"name\": \"Filesystem (reports)\",
    \"server_spec_id\": \"$SPEC_ID\",
    \"json_spec\": {\"type\": \"docker\", \"image\": \"mcp/filesystem:latest\", \"environment\": {\"ALLOWED_DIRECTORIES\": \"/reports\"}}
  }"
```

### Trigger verification

Verification provisions the workload and polls `tools/list` until it answers.
Run it explicitly after creating an instance:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID/verify" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq
```

The call returns 200 whether or not verification succeeded — the HTTP status
describes the call, not the outcome. Read `verification.status`.

A cold `npx` or `uvx` install can take minutes. Verification does not fail on a
clock while the container is alive; it fails early only when the runtime reports
the container dead, and is capped at 600 seconds.

## Verify

The instance is usable when its verification succeeded and it discovered tools:

```bash
curl -s "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '{status: .verification.status, at: .verification.at, tools: (.tools | length)}'
```

```json
{
  "status": "succeeded",
  "at": "2026-07-29T10:22:18.402117+00:00",
  "tools": 11
}
```

`succeeded` with a non-zero tool count means the server answered `tools/list`.
There is no status column — this field is the liveness signal.

## Troubleshooting

**`verification.status` is `failed` with `code: container_failed`.** The
workload started and died. The message carries the runtime's report — usually a
missing environment variable the image requires at boot, or an image that does
not exist for the node's architecture. Fix the spec and re-verify.

**`failed` with `code: list_tools_timeout`.** The container is alive after 600
seconds but never answered `tools/list`. Common causes: the image is not an MCP
server, or it speaks stdio and was configured as `type: "docker"` rather than
being launched through the bridge as `type: "command"`.

**`failed` with `code: mcp_error`.** The endpoint answered but the MCP handshake
failed. This is a protocol-level error and is not retried. Check the server's
own logs.

**Stuck at `in_progress`.** A verification interrupted by a worker restart stays
`in_progress` until it is 12 minutes old, then the monitor marks it
`verification_interrupted`. Re-running `POST .../verify` forces a fresh run
without waiting.

**`never_attempted` and nothing happens.** The background sweep picks up managed
instances at `never_attempted` every 30 seconds, five at a time — unless the
instance is marked `lazy_provisioning`, which is excluded from the sweep by
design and starts on first use instead.

**The instance verifies but an agent cannot call it.** Discovery is separate
from authorization. A tool call also has to clear the task's policy, so check
[Authorize a tool call](/guides/governance/authorize-a-tool-call).

## Related

- [Connect a remote MCP server](/guides/mcp/connect-a-remote-server)
- [Pass secrets to an MCP server](/guides/mcp/pass-secrets)
- [MCP](/concepts/integration/mcp)
