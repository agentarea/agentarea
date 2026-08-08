---
title: Cancel and retry a task
type: guide
summary: Stop a running task, pause and resume it, grant more budget or iterations to one waiting on a limit, and understand why there is no retry endpoint.
prerequisites:
  - /concepts/execution/tasks
related:
  - /guides/tasks/start-a-task
  - /guides/tasks/debug-a-failed-task
  - /concepts/execution/durable-execution
last_updated: 2026-07-29
---

# Cancel and retry a task

Do this when a run is going the wrong way, is costing more than you expected, or
has stopped because it hit a limit. Which control you reach for depends on
whether you want the run to end, to hold, or to keep going with more room.

There is no retry endpoint. Retrying means starting a new task.

## Prerequisites

- A task id and its agent id.
- An API key for the owning workspace.
- Know the task's current status. `GET /v1/agents/{agent_id}/tasks/{task_id}`
  returns it, reconciled against the workflow.

## Choose a control

| Option | Pick it when |
|---|---|
| `DELETE /v1/agents/{agent_id}/tasks/{task_id}` | You want the run stopped now and do not want its result. |
| `POST .../tasks/{task_id}/pause` and `/resume` | You want to inspect state mid-run and continue afterwards. |
| `POST /v1/tasks/{task_id}/continue` | The task is `waiting_for_continuation` and you want it to keep going. |
| `POST .../tasks/{task_id}/command` | You want to change the model, adjust budget, or queue a message into a live run. |
| Start a new task | The run failed and you want another attempt. |

## Steps

### Cancel

```bash
curl -s -X DELETE "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

```json
{
  "status": "cancelled",
  "task_id": "3f2a8c11-...",
  "execution_id": "task-3f2a8c11-..."
}
```

This cancels the Temporal workflow. It does not write `cancelled` to the task
row. Reads that reconcile against the workflow report `cancelled`; a plain list
query still shows the last persisted status. See Verify below.

### Pause and resume

```bash
curl -s -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/pause" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"

curl -s -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/resume" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

The workflow parks between iterations. It holds its conversation, budget
counter, and pending approvals, and consumes no worker slot while paused.

### Continue a task waiting on a limit

A task that exhausts its iteration budget or its spend cap does not fail
immediately. It writes `waiting_for_continuation`, emits
`task.awaiting_continuation`, and idles for up to 24 hours.

The grant must match the reason it stopped:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/tasks/$TASK_ID/continue" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"additional_iterations": 20}'
```

```json
{
  "accepted": true,
  "continuation_count": 1,
  "max_iterations": 30,
  "budget_usd": "10.00"
}
```

For a budget stop, send `additional_budget_usd`. Send both if you are unsure:

```bash
curl -s -X POST "$AGENTAREA_URL/v1/tasks/$TASK_ID/continue" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"additional_iterations": 20, "additional_budget_usd": "5.00"}'
```

Note the path: this one is **not** nested under the agent.

### Steer a running task

`POST /v1/agents/{agent_id}/tasks/{task_id}/command` takes four commands. Each
requires its own field:

| `command` | Required field | Effect |
|---|---|---|
| `change_model` | `model_instance_id` | Switch the model for the remaining iterations. |
| `update_budget` | `budget_usd` | Set a new absolute spend ceiling. Cannot go below what has already been spent. |
| `queue_message` | `message` | Inject a user message before the next model call. |
| `remove_message` | `message_id` | Drop a queued message before the agent sees it. |

```bash
curl -s -X POST "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/command" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"command": "update_budget", "budget_usd": "25.00"}'
```

```json
{"status": "accepted", "command": "update_budget"}
```

### Retry

Start a new task with the same body. A failed task cannot be resumed: its
workflow has terminated, and the task row is the record of that attempt. Reuse
the original `description` and `parameters` from
`GET /v1/agents/{agent_id}/tasks/{task_id}`.

A task that completed is different — it stays alive for 30 minutes accepting
follow-ups. Send `queue_message` rather than starting a new task if you want to
continue the same conversation.

## Verify

After cancelling, confirm the task reports a terminal status through the
reconciling read:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '{status, failure_reason}'
```

```json
{
  "status": "cancelled",
  "failure_reason": null
}
```

After continuing, confirm the grant took by checking that the task left the
waiting state:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq -r '.status'
```

```
running
```

## Troubleshooting

**409 "Task is not running" from a command.** The workflow is no longer running,
so the signal could not be delivered. This is deliberately an error rather than
a misleading 200 — a model switch that never reached the workflow must not look
like it succeeded. Check the status first.

**409 from `/continue` with `not_waiting_for_continuation`.** The task is not in
`waiting_for_continuation`. Either it never hit a limit, or the 24-hour window
expired and it already failed.

**409 with `additional_iterations_required` or `additional_budget_required`.**
The grant did not match the stop reason. A task stopped on `iteration_limit`
needs iterations; one stopped on `budget_exceeded` needs budget. Read
`failure_reason` from the task to see which.

**422 from `/continue`.** Both `additional_iterations` and
`additional_budget_usd` were absent or zero. At least one resource must be
granted.

**404 from `DELETE` on a task you can see.** The endpoint returns 404 when the
workflow could not be cancelled, which includes a task that already reached a
terminal state. A completed task has nothing to cancel.

**The list view still shows `running` after a successful cancel.** Expected. The
cancel path does not write the row; only reads that reconcile against the
workflow report the terminal status. Fetch the single task rather than trusting
a list.

**`update_budget` returns 400.** A new ceiling below the amount already spent is
rejected by the workflow. Query the current cost from
`GET /v1/agents/{agent_id}/tasks/{task_id}/summary` and set a higher value.

## Related

- [Tasks](/concepts/execution/tasks)
- [Debug a failed task](/guides/tasks/debug-a-failed-task)
- [Durable execution](/concepts/execution/durable-execution)
