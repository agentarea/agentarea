---
title: Charge your users for task cost
type: guide
description: "Read what each task and each turn cost in model spend and tokens, attributed to your own end user, from the task, its terminal events, or a signed webhook."
prerequisites:
  - /guides/tasks/start-a-task
related:
  - /guides/tasks/stream-events
  - /reference/mcp-tool-call-context
  - /guides/governance/set-a-budget
last_updated: 2026-10-12
---

Do this when your app runs AgentArea tasks on behalf of its own users and bills
them for it. AgentArea reports what a task cost; deciding the price is yours.

## Prerequisites

<Info>
- An API key or service client. Only those callers may set `end_user_id`,
  `metadata` and `webhook` on a task, and only they read `end_user_id` and
  `metadata` back. A browser session gets 403 setting them and `null` reading
  them.
- For the webhook: an HTTPS endpoint the deployment's outbound policy lets the
  worker reach, and a secret of 32 to 512 characters.
</Info>

## The numbers

| Field | Where | Meaning |
|---|---|---|
| `total_cost` | Task read (`GET …/tasks/{task_id}`, lists), `task.completed`/`task.failed`/`task.cancelled` `data`, webhook body | Model spend of the task so far in USD, including delegated child tasks. A decimal string on events and webhooks, a number on the task read |
| `total_tokens` (task read) / `tokens_used` (events, webhook) | Same | Model tokens of the task so far |
| `end_user_id`, `metadata` | Task read (API callers only), webhook body | What you set when you created the task |

A task that takes follow-ups ends every turn with `task.completed`
(`data.execution_status: "waiting"`), and each turn's `total_cost` and
`tokens_used` are the **running totals of the task**. Charge the difference
from the last value you processed for that task.

`execution_status` says what the run does after the event: `waiting` (it takes
a follow-up), `completed` (it ended), or `settling` on `task.cancelled` (it is
still recording the call the cancel interrupted; a later delivery does not
follow, and `total_cost` can still grow by that call's cost on the task read).

## Steps

<Steps titleSize="h3">
  <Step title="Tag the task with your end user and ask for a webhook">
    ```bash
    curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/agents/$AGENT_ID/tasks/sync" \
      -H "Authorization: Bearer $AGENTAREA_API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "description": "Посчитай смету по плану",
        "end_user_id": "user-42",
        "metadata": {"chatId": "c-9"},
        "webhook": {"url": "https://app.example.com/agentarea/webhook", "secret": "'"$WEBHOOK_SECRET"'"}
      }'
    ```

    `webhook.secret` is write-only: it goes to the secret manager and is never
    returned. Without it deliveries are unsigned.
  </Step>

  <Step title="Receive the webhook">
    AgentArea POSTs one JSON body per terminal event, `task.completed`,
    `task.failed` or `task.cancelled`:

    ```http
    POST /agentarea/webhook HTTP/1.1
    Content-Type: application/json
    X-AgentArea-Event: task.completed
    X-AgentArea-Delivery: 9e8d…
    X-AgentArea-Signature: t=1760263200,v1=5f0c…

    {"version":"1","type":"task.completed","event_id":"9e8d…","task_id":"3f2a…",
     "agent_id":"9b1d…","execution_id":"task-3f2a…","status":"completed",
     "execution_status":"waiting","end_user_id":"user-42","metadata":{"chatId":"c-9"},
     "total_cost":"0.0123","tokens_used":4200,"result":"…","error":null,
     "failure_reason":null,"timestamp":"2026-10-12T10:00:00+00:00"}
    ```

    Verify before trusting it: recompute HMAC-SHA256 with your secret over
    `<t>.<raw body>`, compare with `v1` in constant time, and reject a `t` more
    than five minutes old. Deduplicate on `X-AgentArea-Delivery` (the event id):
    a delivery that got a 5xx, a 429 or no answer is retried, a 4xx is not.
  </Step>

  <Step title="Or read the task">
    ```bash
    curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/agents/$AGENT_ID/tasks/$TASK_ID" \
      -H "Authorization: Bearer $AGENTAREA_API_KEY" \
      | jq '{status, total_cost, total_tokens, end_user_id, metadata}'
    ```

    `total_cost` and `total_tokens` are written when a turn ends, so a running
    task reads the totals of its last finished turn.
  </Step>
</Steps>

## Verify

Start a task with a webhook pointing at a request bin, wait for the turn to
end, and check one delivery arrived with `X-AgentArea-Event: task.completed`
and a `total_cost` equal to `GET …/tasks/{task_id}`'s.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The task is created with 422 webhook.url">
    The URL is not http(s), or it resolves to an address the deployment's
    outbound policy refuses (private and metadata addresses, unless the
    operator allows them).
  </Accordion>
  <Accordion title="No delivery arrives">
    Deliveries go through the worker's channel delivery stream, so the worker's
    channel delivery consumer must be running. A 4xx from your endpoint is not
    retried.
  </Accordion>
  <Accordion title="Two deliveries for one turn">
    At-least-once: deduplicate on `X-AgentArea-Delivery`.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Stream task events" icon="list-check" href="/guides/tasks/stream-events">
    Read the same terminal events live
  </Card>
  <Card title="MCP tool call context" icon="book" href="/reference/mcp-tool-call-context">
    How end_user_id and metadata reach your tool servers
  </Card>
</Columns>
