---
title: Connect a remote MCP server
type: guide
description: "Point AgentArea at an MCP server somebody else operates, test the endpoint before saving it, and get the transport right."
prerequisites:
  - /concepts/integration/mcp
related:
  - /guides/mcp/add-a-hosted-server
  - /guides/mcp/authenticate-with-oauth
  - /guides/mcp/pass-secrets
last_updated: 2026-07-29
---

Do this when the server already runs at a URL — a vendor's hosted MCP endpoint,
or one your team operates elsewhere. Use
[Add a hosted MCP server](/guides/mcp/add-a-hosted-server) when AgentArea should
run the workload itself.

Nothing is provisioned here. AgentArea stores the endpoint and its credentials,
verifies it answers, and proxies every call so authorization and audit stay
central.

## Prerequisites

<Info>
- An API key for the workspace.
- The server's MCP endpoint URL, reachable from the API over the public
  internet. Private and loopback addresses are refused unless the deployment
  explicitly allows them.
- Any credential the server requires, as an HTTP header. For servers that use
  OAuth, see [Authenticate an MCP server with
  OAuth](/guides/mcp/authenticate-with-oauth) instead.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Test the endpoint before saving it">
    `POST /v1/mcp-server-instances/validate` is stateless — it stores nothing and
    creates nothing. For `type: "url"` it opens an MCP session and calls
    `tools/list` on a 3-second budget.

    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/validate" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "type": "url",
        "endpoint_url": "https://mcp.example.com/mcp",
        "headers": {"Authorization": "Bearer sk-live-..."}
      }'
    ```

    ```json
    {
      "valid": true,
      "errors": [],
      "tool_count": 7,
      "tools": [{"name": "search", "description": "...", "inputSchema": {}}]
    }
    ```

    A `valid: false` here means the URL, the transport, or the credential is wrong,
    and saving it will produce a `failed` instance.
  </Step>

  <Step title="Create the connection">
    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/with-spec" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "server": {
          "name": "Example Search",
          "description": "Vendor-hosted search tools.",
          "remote_url": "https://mcp.example.com/mcp",
          "version": "1.0.0",
          "tags": ["search"],
          "env_schema": [
            {"name": "Authorization", "description": "Bearer token", "isSecret": true}
          ]
        },
        "instance": {
          "name": "Example Search",
          "json_spec": {
            "type": "url",
            "endpoint_url": "https://mcp.example.com/mcp",
            "headers": {"Authorization": "Bearer sk-live-..."}
          }
        }
      }'
    ```

    A `url` instance verifies synchronously, so this returns 201 with the outcome
    already in `verification`. Managed instances return 202 instead, because their
    verification runs in the background.

    The header value does not stay in `json_spec`. Any name marked `isSecret` in the
    spec's `env_schema` is moved into the secret manager and masked on read — see
    [Pass secrets to an MCP server](/guides/mcp/pass-secrets).
  </Step>

  <Step title="Get the transport right">
    AgentArea does not guess when the registry told it the answer. A spec whose
    `json_spec` carries `remotes[].type` is honoured exactly, with no probing and no
    cross-transport fallback.

    For a hand-entered URL the transport is unknown, so suffix heuristics apply:

    | URL ends with | Tried |
    |---|---|
    | `/sse` | SSE only. Use this when the server is SSE-only. |
    | `/mcp` | Streamable HTTP at the URL, then `/sse` as a sibling fallback. |
    | anything else | The URL as given, then `+/mcp`, then `+/sse`. |

    Give the exact canonical endpoint when you know it. Several vendors serve
    Streamable HTTP at the root, and a trailing `/mcp` invented by the heuristics
    404s before the fallback runs.
  </Step>

  <Step title="Re-discover tools after the server changes">
    The tool list is a snapshot from the last successful verification. When the
    vendor adds a tool:

    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID/discover-tools" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```
  </Step>
</Steps>

## Verify

Confirm the instance verified and the agent-facing proxy answers.

```bash
curl -s "$AGENTAREA_URL/v1/mcp-server-instances/$INSTANCE_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '{status: .verification.status, tools: (.tools | length)}'
```

```json
{
  "status": "succeeded",
  "tools": 7
}
```

Then call the governed endpoint, which is the path agents actually use:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/mcp/$INSTANCE_ID/mcp" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

A JSON-RPC result listing tools proves the full path works: AgentArea resolved
the instance, injected the stored credential, and reached the server.

## Troubleshooting

<AccordionGroup>
  <Accordion title='`{"valid": false, "errors": ["URL is not allowed"]}`'>
    The URL resolves to a private, loopback, or link-local address and was
    refused before any request was made. The message is deliberately generic so
    it cannot be used to probe which internal names resolve. For local
    development, list the host or its CIDR in `OUTBOUND_PRIVATE_ALLOWLIST`
    (comma-separated, for example `localhost,10.43.0.0/16`), or set
    `ALLOW_PRIVATE_URLS` to allow every private address.
  </Accordion>
  <Accordion title="`Authentication failed — check your credentials`">
    The server returned 401. The credential is wrong, expired, or the header
    name does not match what the server expects — `Authorization` and
    `X-API-Key` are not interchangeable.
  </Accordion>
  <Accordion title="`Access denied — insufficient permissions`">
    The server returned 403. The credential is valid but not scoped for
    `tools/list` .
  </Accordion>
  <Accordion title="Validation succeeds but the instance verifies as `failed`">
    Validation used the headers in your request body; the instance uses the
    headers stored on it. If `env_schema` marked the header secret, confirm the
    value was saved — read
    `GET /v1/mcp-server- instances/{instance_id}/environment` to see which names
    have values.
  </Accordion>
  <Accordion title="The instance verifies but calls through `/v1/mcp/{instance_id}/mcp` fail">
    The proxy is Streamable HTTP only. A server that verified over the SSE
    fallback cannot be proxied. Use a Streamable HTTP endpoint, or attach the
    instance to a client bundle, which aggregates over its own transport.
  </Accordion>
  <Accordion title="Tools disappear or go stale">
    Nothing re-verifies a healthy instance on a schedule. A server that changed
    or went down keeps reporting its last `succeeded` snapshot until you
    re-verify or re-discover.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Add a hosted MCP server" icon="plug" href="/guides/mcp/add-a-hosted-server">
    Run an MCP server as a managed workload
  </Card>
  <Card title="Authenticate an MCP server with OAuth" icon="plug" href="/guides/mcp/authenticate-with-oauth">
    Connect a remote MCP instance to a provider that requires OAuth
  </Card>
  <Card title="MCP" icon="plug" href="/concepts/integration/mcp">
    What the Model Context Protocol gives an agent, and how AgentArea hosts MCP
    servers
  </Card>
</Columns>
