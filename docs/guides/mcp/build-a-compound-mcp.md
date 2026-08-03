---
title: Combine several MCP servers behind one endpoint
type: guide
summary: Aggregate the tools of several MCP instances into a single namespaced endpoint by attaching them to a registered client, then point a harness at it.
prerequisites:
  - /guides/mcp/add-a-hosted-server
related:
  - /guides/mcp/connect-a-remote-server
  - /guides/mcp/issue-access-tokens
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Combine several MCP servers behind one endpoint

Do this when a client — a Codex or Claude harness, an IDE, another agent — should
see one MCP endpoint that exposes tools drawn from several servers. Do not do
this to give an AgentArea agent tools; an agent is configured with its own tool
list and does not need an aggregate.

The mechanism is a **registered client**. A client is a governable entity that
owns a set of MCP instances and skills, and gets a single MCP endpoint that
merges them. There is no separate "compound MCP" resource in the API — earlier
drafts of these docs described a compound-mcps collection that was never part of
the shipped surface.

## Prerequisites

- Two or more MCP server instances that verified successfully. An instance whose
  URL cannot be resolved is skipped from the bundle silently, so verify first
  with [Add a hosted MCP server](/guides/mcp/add-a-hosted-server).
- An API key for the workspace.
- Optionally a project, if you want several clients to share one curated set.

## Choose how members are supplied

| Option | Pick it when |
|---|---|
| Attach instances directly to the client | The bundle is specific to one harness. |
| Point the client at a source project | Several clients should share one curated set, maintained in one place. |
| Both | The client needs the shared project set plus one or two extras of its own. |

The effective set is the union of the client's own attachments and those of its
source project, so "both" needs no extra configuration.

## Steps

### 1. Create the client

```bash
curl -s -X POST "$AGENTAREA_URL/v1/clients/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "codex-laptop", "kind": "harness", "description": "Local Codex harness"}'
```

```json
{
  "id": "b4c8f210-...",
  "workspace_id": "ws-1",
  "created_by": "user-1",
  "name": "codex-laptop",
  "description": "Local Codex harness",
  "kind": "harness",
  "source_project_id": null,
  "skills": [],
  "mcp_instances": [],
  "mcp_endpoint_url": "https://api.example.com/client-mcp/b4c8f210-..."
}
```

`mcp_endpoint_url` is the aggregate. Note it is served at `/client-mcp/{client_id}`
— outside `/v1`, because it is a mounted MCP application rather than a REST route.

### 2. Attach instances, with a namespace each

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST "$AGENTAREA_URL/v1/clients/$CLIENT_ID/mcp-instances" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"id\": \"$GITHUB_INSTANCE_ID\", \"namespace_prefix\": \"gh\"}"
```

```
204
```

Repeat per member. `namespace_prefix` decides the tool prefix: a `search` tool on
the instance namespaced `gh` is exposed as `gh__search`. Two members that both
expose `search` stay distinguishable only if their namespaces differ, so set the
prefix deliberately rather than leaving it null.

### 3. Or inherit from a project

```bash
curl -s -X POST "$AGENTAREA_URL/v1/clients/$CLIENT_ID/pull-from-project" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"project_id\": \"$PROJECT_ID\"}"
```

Curate the project's members with
`POST /v1/projects/{project_id}/mcp-instances`. Every client pointing at that
project picks up changes without being touched.

### 4. Attach skills, if the client should have them

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -X POST "$AGENTAREA_URL/v1/clients/$CLIENT_ID/skills" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"id\": \"$SKILL_ID\"}"
```

When a client has skills, the aggregate exposes an extra `activate_skill` tool
whose enum lists them, alongside the namespaced member tools.

### 5. Point the harness at the endpoint

Give the harness `mcp_endpoint_url` and a token. Access is checked on every
request: the token's subject must be the client itself, or a principal holding
the `use` relation on that client. See [Issue MCP access
tokens](/guides/mcp/issue-access-tokens).

## Verify

List the tools through the aggregate. This is the same call the harness makes.

```bash
curl -s -X POST "$AGENTAREA_URL/client-mcp/$CLIENT_ID" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' \
  | jq '.result.tools[].name'
```

```
"gh__search"
"gh__create_issue"
"fs__read_file"
"activate_skill"
```

Namespaced names from more than one member prove the aggregation resolved. Then
call one to prove forwarding works:

```bash
curl -s -X POST "$AGENTAREA_URL/client-mcp/$CLIENT_ID" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "gh__search", "arguments": {"query": "openapi"}}}'
```

## Troubleshooting

**`tools/list` returns an empty array.** Either the client id in the path does
not exist, or no member resolved. A member whose URL cannot be resolved is
skipped and logged rather than failing the whole bundle, so one broken instance
looks like a missing tool rather than an error. Check each member's
`verification.status` individually.

**"Not authorized for this client".** The token's subject is neither the client
nor a principal with `use` on it. A workspace API key is not automatically
authorized for a client bundle.

**Tool names collide.** Two members exposing the same tool name with the same or
null namespace produce ambiguous entries. Set a distinct `namespace_prefix` on
each member.

**A tool that exists on the server is missing from the aggregate.** Member tools
come from each instance's stored snapshot, discovered at its last verification.
Run `POST /v1/mcp-server-instances/{instance_id}/discover-tools` on the member,
then list again.

**Removing an instance from the project does not change the client.** It does,
but only for members the client inherited. An instance attached directly to the
client stays until you `DELETE /v1/clients/{client_id}/mcp-instances/{mcp_instance_id}`.
The effective set is a union, so a direct attachment shadows a project removal.

**The endpoint 404s.** `/client-mcp/{client_id}` is a mounted application, not a
`/v1` route, and it is absent from the OpenAPI spec for that reason. Use the
`mcp_endpoint_url` from the client response rather than assembling the path from
the API base by hand.

## Related

- [Add a hosted MCP server](/guides/mcp/add-a-hosted-server)
- [Issue MCP access tokens](/guides/mcp/issue-access-tokens)
- [MCP](/concepts/integration/mcp)
