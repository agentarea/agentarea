---
title: Debug a failed task
type: guide
summary: Read the failure code, narrow it with the task rollup, then find the exact event that broke the run.
prerequisites:
  - /concepts/execution/tasks
related:
  - /guides/tasks/stream-events
  - /guides/tasks/cancel-and-retry
  - /guides/tasks/retrieve-artifacts
  - /concepts/execution/events
last_updated: 2026-07-29
---

# Debug a failed task

Do this when a task ended in `failed` or `blocked` and you need to know why.
Work top-down: the failure code narrows the search to one class of problem, the
rollup tells you where in the run it happened, and the event log gives you the
exact call.

Do not start from the event log. A long run has hundreds of events and the
failure code eliminates most of them in one request.

## Prerequisites

- The task id and its agent id.
- An API key for the owning workspace.

## Steps

### 1. Read the failure code

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '{status, failure_reason, error, total_cost}'
```

```json
{
  "status": "failed",
  "failure_reason": "validation_failed",
  "error": "Artifact validation failed after two repair attempts",
  "total_cost": 0.4312
}
```

`error` is the human-readable message. `failure_reason` is the stable code, and
it is what you route on:

| `failure_reason` | What happened | Where to look next |
|---|---|---|
| `iteration_limit` | Ran out of iterations before finishing. | Rollup: `iterations`. Grant more with `/continue`. |
| `budget_exceeded` | Hit the spend ceiling. | Rollup: `cost_usd`. Grant more with `/continue`. |
| `validation_failed` | The agent claimed completion but its artifacts did not validate, twice. | `artifact.validation.completed` events. |
| `capability_unavailable` | A required capability could not run. Status is `blocked`, not `failed`. | `last_error` in the rollup. |
| `missing_final_response` | The agent completed without producing a final answer. | The last `llm.call.completed` event. |
| `task_unsuccessful` | The loop ended without success and without a more specific cause. | Rollup, then the event log. |

A `blocked` status with `capability_unavailable` is not a model failure — it is
the platform refusing to certify success it could not check.

### 2. Narrow with the rollup

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/summary" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq
```

```json
{
  "task_id": "3f2a8c11-...",
  "agent_id": "9b1d...",
  "workspace_id": "ws-1",
  "status": "failed",
  "started_at": "2026-07-29T10:15:04.912004+00:00",
  "ended_at": "2026-07-29T10:19:41.220118+00:00",
  "duration_ms": 276308.114,
  "iterations": 10,
  "llm_calls": 10,
  "llm_calls_failed": 0,
  "tools_called": 23,
  "tools_failed": 7,
  "delegations_started": 0,
  "delegations_completed": 0,
  "delegations_failed": 0,
  "cost_usd": 0.4312,
  "final_response": null,
  "last_error": "bash: command not found: pandoc"
}
```

Read it as a triage table:

- `tools_failed` high relative to `tools_called` — the agent is fighting its
  tools. Go to the tool events.
- `llm_calls_failed` above zero — a provider problem. Go to the LLM events.
- `iterations` equal to the cap with `tools_failed` at zero — the agent is
  looping without progress. Read the conversation.
- `last_error` is usually the single most useful field on the page.

### 3. Find the failing event

Filter the durable log rather than reading all of it:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events?event_type=tool.result&page_size=100" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '.events[] | select(.metadata.error != null) | {timestamp, event_type, message, metadata}'
```

Useful filters:

| `event_type` | Answers |
|---|---|
| `tool.result` | Which tool call failed, with its exit code. |
| `llm.call.failed` | Provider errors, with the retryable flag. |
| `artifact.validation.completed` | Which artifact failed validation and why. |
| `approval.request` | Whether the run stalled waiting on a human. |
| `task.failed` | The terminal message and reason. |

The full history is paginated; `has_next` tells you when to advance `page`.

### 4. Check what the agent produced

A failed task can still have written files. They are often the fastest way to
see what it was doing:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/artifacts" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.[].path'
```

### 5. If the failure looks like a permission denial

Tool calls blocked by policy fail with a denial rather than an error from the
tool. Read the policy the task actually ran under — the resolved snapshot, not a
re-resolution:

```bash
curl -s "$AGENTAREA_URL/v1/governance/task-policy-snapshots/$TASK_ID" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq
```

## Verify

You have finished debugging when you can name the failure code and point at the
event that produced it. Confirm the two agree:

```bash
curl -s "$AGENTAREA_URL/v1/agents/$AGENT_ID/tasks/$TASK_ID/events?event_type=task.failed" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq -r '.events[-1].message'
```

```
Artifact validation failed after two repair attempts
```

This message matches `error` on the task. If they disagree, the task row was
reconciled from the workflow after the event was written — trust the task row.

## Troubleshooting

**`failure_reason` is null on a failed task.** The task failed before the
workflow could record a reason, most often a dispatch failure. Check
`execution_id`: null means no workflow ever started, and `error` will carry the
submission error instead.

**404 from `/summary` on a task that `GET .../tasks/{task_id}` returns.** The
rollup is backed by the `task_summary` view, which is keyed on task, workspace,
and agent together. A task fetched with the wrong `agent_id` in the path 404s
here even though the task exists.

**The event log is empty but the task ran.** Events are written by an activity
that records its own database failures without failing the batch, so a database
problem during the run leaves gaps. The task row and the rollup are still
authoritative for the outcome.

**A task shows `blocked` but the stream ended with `task.failed`.** There is no
`task.blocked` event type. The feed reports `task.failed` for any unsuccessful
end; the row carries the more specific status and `failure_reason`.

**A task is stuck at `running` and nothing is happening.** There is no
wall-clock timeout on a task — the only stop conditions are goal achieved,
iteration limit, and budget. Check `GET .../tasks/{task_id}/status` for the live
workflow state, then cancel it if the workflow is gone.

**Cost reads zero on a task that clearly called a model.** `total_cost` is
written at terminal status. A task killed before finalization keeps the last
persisted value; use `cost_usd` from the rollup, which is derived from the event
log.

## Related

- [Stream task events](/guides/tasks/stream-events)
- [Cancel and retry a task](/guides/tasks/cancel-and-retry)
- [Tasks](/concepts/execution/tasks)
