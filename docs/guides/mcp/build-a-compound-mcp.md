---
title: Combine several MCP servers behind one endpoint
type: guide
description: "Aggregate MCP instances and AgentArea platform toolsets into a single namespaced endpoint by attaching them to a registered client, then point a harness at it."
prerequisites:
  - /guides/mcp/add-a-hosted-server
related:
  - /guides/mcp/connect-a-harness-to-agentarea
  - /guides/mcp/connect-a-remote-server
  - /guides/mcp/issue-access-tokens
  - /concepts/integration/mcp
last_updated: 2026-10-01
---

Do this when a client — a Codex or Claude harness, an IDE, another agent — should
see one MCP endpoint that exposes tools drawn from several servers, or a chosen
part of AgentArea's own platform tools. Do not do this to give an AgentArea agent
tools; an agent is configured with its own tool list and does not need an
aggregate.

The mechanism is a **registered client** (shown as a *harness* in the web app).
A client is a governable entity that owns a set of MCP instances, platform
toolsets, and skills, and gets a single MCP endpoint that merges them. There is
no separate "compound MCP" resource in the API — earlier drafts of these docs
described a compound-mcps collection that was never part of the shipped surface.

## Prerequisites

<Info>
- Two or more MCP server instances that verified successfully. An instance whose
  URL cannot be resolved is skipped from the bundle silently, so verify first
  with [Add a hosted MCP server](/guides/mcp/add-a-hosted-server).
- An API key for the workspace.

A client's bundle is exactly what is attached to it. Several harnesses that
should share one set each get their own attachments; there is no inheritance
from another entity.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Create the client">
    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/" \
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
      "skills": [],
      "mcp_instances": [],
      "platform_toolsets": [],
      "mcp_endpoint_url": "https://api.example.com/mcp/clients/b4c8f210-..."
    }
    ```

    `mcp_endpoint_url` is the aggregate. Note it is served at `/mcp/clients/{client_id}`
    — outside `/v1`, because it is a mounted MCP application rather than a REST route.
  </Step>

  <Step title="Attach instances, with a namespace each">
    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' \
      -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/$CLIENT_ID/mcp-instances" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"id\": \"$GITHUB_INSTANCE_ID\", \"namespace_prefix\": \"gh\", \"allowed_tools\": [\"search\", \"create_issue\"]}"
    ```

    ```text
    204
    ```

    Repeat per member. `namespace_prefix` decides the tool prefix: a `search` tool on
    the instance namespaced `gh` is exposed as `gh__search`. Two members that both
    expose `search` stay distinguishable only if their namespaces differ, so set the
    prefix deliberately rather than leaving it null.

    `allowed_tools` names the instance's own tools (without the prefix) the client
    serves; omit it or send `null` to serve all of them. A tool left out is neither
    listed nor callable through the endpoint. Posting the same instance again
    replaces both `namespace_prefix` and `allowed_tools`, so send both every time.
  </Step>

  <Step title="Attach platform toolsets, if the harness should manage AgentArea">
    List the toolsets a client can carry and the methods of each:

    ```bash
    curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/platform-toolsets" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq -r '.[].name'
    ```

    Attach one by namespace, leaving out the methods the harness should not see:

    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' \
      -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/$CLIENT_ID/platform-toolsets" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "agentarea/runs", "disabled_methods": ["cancel"]}'
    ```

    ```text
    204
    ```

    The endpoint then serves the toolset's tools under their platform names
    (`runs_list`, `runs_start`, ...), minus `disabled_methods`. They run in the
    client's workspace as the calling principal, so each call is authorized
    exactly as it would be on the platform's own MCP server; carrying a toolset
    grants nothing the caller could not already do. Posting the same toolset
    again replaces `disabled_methods`. Detach one with
    `DELETE /v1/workspaces/{workspace}/clients/{client_id}/platform-toolsets/{namespace}`.
  </Step>

  <Step title="Attach skills, if the client should have them">
    ```bash
    curl -s -o /dev/null -w '%{http_code}\n' \
      -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/$CLIENT_ID/skills" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"id\": \"$SKILL_ID\"}"
    ```

    When a client has skills, the aggregate exposes an extra `activate_skill` tool
    whose enum lists them, alongside the namespaced member tools.
  </Step>

  <Step title="Point the harness at the endpoint">
    Give the harness `mcp_endpoint_url` and a token. Access is checked on every
    request: the token's subject must be the client itself, or a principal holding
    the `use` relation on that client. See [Issue MCP access
    tokens](/guides/mcp/issue-access-tokens).
  </Step>
</Steps>

## Verify

List the tools through the aggregate. This is the same call the harness makes.

```bash
curl -s -X POST "$AGENTAREA_URL/mcp/clients/$CLIENT_ID" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' \
  | jq '.result.tools[].name'
```

```text
"gh__search"
"gh__create_issue"
"fs__read_file"
"runs_list"
"runs_start"
"activate_skill"
```

Namespaced names from more than one member prove the aggregation resolved. Then
call one to prove forwarding works:

```bash
curl -s -X POST "$AGENTAREA_URL/mcp/clients/$CLIENT_ID" \
  -H "Authorization: Bearer $CLIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "gh__search", "arguments": {"query": "openapi"}}}'
```

## Troubleshooting

<AccordionGroup>
  <Accordion title="`tools/list` returns an empty array">
    Either the client id in the path does not exist, or no member resolved. A
    member whose URL cannot be resolved is skipped and logged rather than
    failing the whole bundle, so one broken instance looks like a missing tool
    rather than an error. Check each member's `verification.status`
    individually.
  </Accordion>
  <Accordion title='"Not authorized for this client"'>
    The token's subject is neither the client nor a principal with `use` on it.
    A workspace API key is not automatically authorized for a client bundle.
  </Accordion>
  <Accordion title="Tool names collide">
    Two members exposing the same tool name with the same or null namespace
    produce ambiguous entries. Set a distinct `namespace_prefix` on each member.
    Platform tools never collide with member tools: member tools always carry a
    `__` separator, platform tools never do.
  </Accordion>
  <Accordion title="Attaching a platform toolset returns 422">
    The name is not a toolset a client can carry, or `disabled_methods` names a
    method the toolset does not have. The response lists the valid names. The
    `workspaces` toolset is not carried: a client always acts in its own
    workspace.
  </Accordion>
  <Accordion title="A tool the instance has is missing from the aggregate">
    The attachment's `allowed_tools` leaves it out. The list names exactly what
    is served, so a tool the instance gained after you narrowed it stays out
    until you add it. The web app's checklist shows the instance's stored tool
    snapshot from its last verification; if the tool is missing there too, run
    `POST /v1/workspaces/{workspace}/mcp-server-instances/{instance_id}/discover-tools`
    on the member, then reopen the harness.
  </Accordion>
  <Accordion title="A member is still exposed after you removed it elsewhere">
    Members are only ever the client's own attachments. Remove one with
    `DELETE /v1/workspaces/{workspace}/clients/{client_id}/mcp-instances/{mcp_instance_id}` .
  </Accordion>
  <Accordion title="The endpoint 404s">
    `/mcp/clients/{client_id}` is a mounted application, not a `/v1` route, and
    it is absent from the OpenAPI spec for that reason. Use the
    `mcp_endpoint_url` from the client response rather than assembling the path
    from the API base by hand.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Add a hosted MCP server" icon="plug" href="/guides/mcp/add-a-hosted-server">
    Run an MCP server as a managed workload
  </Card>
  <Card title="Connect a harness to AgentArea" icon="plug" href="/guides/mcp/connect-a-harness-to-agentarea">
    Manage AgentArea itself over MCP, with only the toolsets you need
  </Card>
  <Card title="Issue MCP access tokens" icon="plug" href="/guides/mcp/issue-access-tokens">
    Create, scope, rotate, and revoke the API keys that authenticate calls to
    MCP endpoints and the
  </Card>
  <Card title="MCP" icon="plug" href="/concepts/integration/mcp">
    What the Model Context Protocol gives an agent, and how AgentArea hosts MCP
    servers
  </Card>
</Columns>
