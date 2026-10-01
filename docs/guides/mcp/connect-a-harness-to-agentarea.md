---
title: Connect a harness to AgentArea over MCP
type: guide
description: "Point Claude Code, Codex, or another MCP client at AgentArea's own MCP server, pinned to one workspace and narrowed to the toolsets the harness needs."
prerequisites:
  - /guides/mcp/issue-access-tokens
related:
  - /guides/mcp/build-a-compound-mcp
  - /concepts/integration/mcp
  - /guides/mcp/issue-access-tokens
last_updated: 2026-10-01
---

Do this when a harness should manage AgentArea itself — start and steer runs,
edit agents, wire triggers — through MCP. Pass `?toolsets=` so the harness
loads only the toolsets it uses: without it, every platform tool is listed, and
each one costs the harness context whether it is called or not.

AgentArea serves its platform tools at two URLs:

| URL | Workspace | Tool arguments |
|---|---|---|
| `/mcp` | Every workspace the caller can reach | Each workspace-scoped tool takes a required `workspace` (slug or id); `workspaces_list` finds them |
| `/mcp/w/{workspace}` | The one the URL names, by slug or id | No `workspace` argument |

Prefer the pinned URL for a harness that works in one workspace: the tools are
smaller and the model cannot act in the wrong workspace.

## Prerequisites

<Info>
- An API key, or an MCP client that completes OAuth on its own. See [Issue MCP
  access tokens](/guides/mcp/issue-access-tokens).
- The slug of the workspace the harness works in.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Pick the toolsets">
    List the toolsets the pinned URL serves, with how many tools each adds:

    ```bash
    curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/clients/platform-toolsets" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      | jq -r '.[] | "\(.name)\t\(.methods | length)\t\(.description)"'
    ```

    ```text
    agentarea/agents	5	Create, list, update, and delete agents in the workspace.
    agentarea/runs	12	Start, monitor, and manage agent execution runs.
    agentarea/inbox	1	Inspect agent inbox messages awaiting human input.
    ```

    A toolset is selected by its namespace or by its name, the last segment of
    the namespace and the prefix of its tools: `runs` serves `runs_list`,
    `runs_start`, and the rest. The bare `/mcp` URL also has `workspaces`.
  </Step>

  <Step title="Add the server to the harness">
    Append the names, comma-separated, to the URL. For Claude Code with an API
    key:

    ```bash
    claude mcp add --transport http agentarea \
      "$AGENTAREA_URL/mcp/w/$WORKSPACE/?toolsets=runs,agents,inbox" \
      --header "Authorization: Bearer $AGENTAREA_TOKEN"
    ```

    Any client that can store a server URL works the same way; the selection
    lives in the URL, so no client-specific header is needed.
  </Step>
</Steps>

## Verify

List the tools through the same URL the harness uses:

```bash
curl -s -X POST "$AGENTAREA_URL/mcp/w/$WORKSPACE/?toolsets=runs,agents,inbox" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' \
  | sed -n 's/^data: //p' | jq -r '.result.tools[].name'
```

Every name starts with `runs_`, `agents_`, or `inbox_`. A tool of any other
toolset is not listed, and calling it answers the way a call to a tool the
server never had does: an error result reading `Unknown tool: <name>`.

## Troubleshooting

<AccordionGroup>
  <Accordion title="HTTP 400 with JSON-RPC error -32602">
    `toolsets` names a toolset the server does not have, or names none at all
    (`?toolsets=`). The message lists the valid names. Unknown names are
    refused rather than skipped, so a typo cannot silently leave the harness
    with fewer tools than you configured.
  </Accordion>
  <Accordion title="HTTP 403 from a pinned URL">
    The workspace in the URL does not exist or the token's principal is not a
    member of it. Both answer the same way, so the response does not reveal
    which workspaces exist.
  </Accordion>
  <Accordion title="The harness needs tools from MCP servers too">
    One URL serves only platform toolsets. To give a harness platform toolsets
    and MCP server tools behind one endpoint, with the selection stored on the
    server instead of in each harness's URL, register a client and attach both:
    [Combine several MCP servers behind one endpoint](/guides/mcp/build-a-compound-mcp).
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Combine several MCP servers" icon="plug" href="/guides/mcp/build-a-compound-mcp">
    One harness endpoint for MCP instances and platform toolsets
  </Card>
  <Card title="Issue MCP access tokens" icon="plug" href="/guides/mcp/issue-access-tokens">
    Create and scope the keys that authenticate MCP calls
  </Card>
  <Card title="MCP" icon="lightbulb" href="/concepts/integration/mcp">
    How AgentArea hosts and governs MCP servers
  </Card>
</Columns>
