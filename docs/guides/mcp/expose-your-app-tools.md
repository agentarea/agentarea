---
title: Expose your app's tools to agents
type: guide
description: "Serve your application's own actions as an MCP server, connect it with a signing secret, and start tasks that tell each tool call which end user it is for."
prerequisites:
  - /concepts/integration/mcp
  - /guides/mcp/connect-a-remote-server
related:
  - /reference/mcp-tool-call-context
  - /guides/tasks/start-a-task
  - /guides/tasks/stream-events
  - /guides/mcp/pass-secrets
last_updated: 2026-10-12
---

Do this when an agent should act inside your own product (read an order, post
into a chat, import a sheet) and the tool must know which task, workspace and
end user the call is for. AgentArea signs that context per call; your server
verifies it and can stream progress back into the task.

Use [Connect a remote MCP server](/guides/mcp/connect-a-remote-server) instead
for a third-party server that does not need to know who a call is for.

## Prerequisites

<Info>
- An API key for the workspace. Only an API key (or a client-credentials
  token) may set `metadata` and `end_user_id` on a task.
- An MCP server over Streamable HTTP that verifies the
  [tool call context](/reference/mcp-tool-call-context). `@agentarea/tools`
  does this for TypeScript; any server can follow the reference.
- Two different random values: a static credential, and a signing secret of at
  least 32 characters.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Serve the tools">
    With `@agentarea/tools`, give the server both values and the instance id it
    will be registered under (`audience`). Until you know the id, start with
    `audience` unset and add it after the next step.

    ```ts
    import { createToolServer, tool } from '@agentarea/tools';
    import * as z from 'zod';

    const server = createToolServer({
      name: 'orders',
      version: '1.0.0',
      auth: {
        bearer: process.env.AGENTAREA_TOOLS_BEARER!,
        secret: process.env.AGENTAREA_TOOLS_SECRET!,
        audience: process.env.AGENTAREA_INSTANCE_ID,
        issuer: 'agentarea',
      },
      tools: {
        import_sheet: tool({
          description: 'Import an order sheet',
          input: z.object({ url: z.string() }),
          execute: async ({ url }, ctx) => {
            await ctx.progress('Reading sheet', { progress: 1, total: 2 });
            // ctx.endUserId and ctx.metadata come from the signed token
            await ctx.progress('Saving rows', { progress: 2, total: 2 });
            return { text: 'Imported 23 rows.', data: { rows: 23 } };
          },
        }),
      },
    });
    ```
  </Step>

  <Step title="Connect it with a signing secret">
    `context_secret` is write-only: it goes to the secret manager and is never
    sent to the server or returned.

    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/mcp-server-instances/with-spec" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "server": {
          "name": "Orders",
          "description": "Our order tools.",
          "remote_url": "https://app.example.com/api/mcp",
          "env_schema": [{"name": "Authorization", "description": "Static credential", "isSecret": true}]
        },
        "instance": {
          "name": "Orders",
          "json_spec": {
            "type": "url",
            "endpoint_url": "https://app.example.com/api/mcp",
            "headers": {"Authorization": "Bearer '"$AGENTAREA_TOOLS_BEARER"'"}
          },
          "context_secret": "'"$AGENTAREA_TOOLS_SECRET"'"
        }
      }' | jq '{id, signing: .json_spec.context_signing, status: .verification.status}'
    ```

    Set the returned `id` as the server's `audience`. To add or rotate the
    secret on an existing instance, `PATCH .../mcp-server-instances/{instance_id}`
    with `{"context_secret": "..."}`; `null` removes it.
  </Step>

  <Step title="Attach the server to an agent">
    Attach the instance like any other MCP server, in the agent's tools.
  </Step>

  <Step title="Start tasks with the end user and metadata">
    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/agents/$AGENT_ID/tasks/sync" \
      -H "Authorization: Bearer $AGENTAREA_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "description": "Import the sheet the user shared",
        "end_user_id": "user-42",
        "metadata": {"chatId": "c-9"}
      }'
    ```

    Every tool call of this task reaches your server with
    `agentarea/end_user_id` and `agentarea/metadata`, signed. The model can
    neither read them from its arguments nor change them.
  </Step>
</Steps>

## Verify

Stream the task and look for progress and the structured result:

```bash
curl -sN "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/agents/$AGENT_ID/tasks/$TASK_ID/events/stream" \
  -H "Authorization: Bearer $AGENTAREA_API_KEY" | grep -E 'tool\.(progress|result)'
```

You see one `tool.progress` per notification (at most two a second per call)
and a `tool.result` whose `data.structured_content` is `{"rows": 23}`. On the
server, `ctx.signed` is `true`.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The tool fails with `rejected the credentials (HTTP 401)`">
    Either the static credential is wrong, or the context token was refused:
    a different secret on each side, `audience` set to something other than the
    instance id, or `issuer` other than `agentarea`. The server's log names the
    failing check.
  </Accordion>
  <Accordion title="The server says `missing x-agentarea-context header`">
    The instance has no `context_secret`, so AgentArea sends no context. Read
    the instance: `json_spec.context_signing` must be `true`.
  </Accordion>
  <Accordion title="`metadata and end_user_id can only be set with an API key` (403)">
    The task was created from a signed-in browser session. Create it with an API
    key.
  </Accordion>
  <Accordion title="The server runs inside your cluster or on localhost">
    Private and cluster-internal addresses are refused unless the operator lists
    them in `AGENTAREA_HTTP_PRIVATE_ALLOWLIST` on the API and the worker, for
    example `orders.apps.svc.cluster.local` or `10.0.4.17/32`. There is no
    per-workspace switch: whoever can create an instance could otherwise reach
    every internal service.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="MCP tool call context" icon="book" href="/reference/mcp-tool-call-context">
    Every key, claim, rejection and limit
  </Card>
  <Card title="Stream task events" icon="wave-pulse" href="/guides/tasks/stream-events">
    Read tool.progress and tool.result live
  </Card>
</Columns>
