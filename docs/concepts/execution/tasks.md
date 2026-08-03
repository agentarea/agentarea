---
title: Tasks
type: concept
summary: A task is one persisted request to one agent; this page gives its identity, its status machine, and which states actually end it.
prerequisites:
  - /agentic-networks
related:
  - /concepts/execution/durable-execution
  - /concepts/execution/events
  - /concepts/execution/artifacts
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Tasks

A task is one request to one agent, written to the database before any model is
called. Everything else in the execution layer hangs off it: the Temporal
workflow that runs it, the event feed you stream, the artifacts it produces, and
the governance policy it was launched under.

## The problem

Without a persisted task, an agent run is a request-scoped side effect. It ends
when the HTTP connection ends, there is nothing to resume after a worker
restart, nothing to attach a spend limit to, no row to join against for an audit
question, and no stable identity for a follow-up message to address. Every
capability the platform sells — durability, governance, streaming, audit —
requires that the run has an identity that outlives the process running it.

## How AgentArea approaches it

A task is created before it is dispatched, and creation is where the expensive
decisions get made. `TaskService.create_task_with_policy` resolves an effective
governance policy for the workspace, agent, user, and task; checks the
workspace's month-to-date spend against the policy cap and raises
`BudgetCapExceededError` if it is already exhausted; verifies the agent exists
and has a model configured; and only then writes the row.

REST, A2A, and the MCP toolset all funnel through the same entry point,
`create_and_execute_task_with_workflow`, so none of them can drift into a
different set of defaults.

### Identity

| Field | Meaning |
|---|---|
| `id` | Task identity. Callers may pre-assign it (A2A echoes it back). |
| `agent_id` | The agent that runs it. Tasks are addressed under the agent: `/v1/agents/{agent_id}/tasks/{task_id}`. |
| `workspace_id`, `user_id` | Tenancy and audit. Both are required; a task missing either is rejected at the manager boundary. |
| `query`, `description` | What the agent is asked to do. |
| `parameters` | Caller input, including `channel_origin` and `success_criteria`. |
| `metadata` | Server-side facts such as `created_via`, `agent_name`, `requires_human_approval`, and `project_id`. Sandbox provider and runtime policy are deliberately absent. |
| `execution_id` | The Temporal workflow id, always `task-{task_id}`. |

### The status machine

Eleven values pass validation (`BaseTaskService._validate_task`). Ten are
written by some path today:

| Status | Written by |
|---|---|
| `submitted` | Default on the domain model; the persist-only path when no status is passed. |
| `preparing` | `reserve_run`, when task-scoped inputs must be committed to storage before dispatch. |
| `pending` | Set immediately before the task is handed to the task manager. |
| `running` | `TemporalTaskManager.submit_task`, once the workflow has started, together with `execution_id`. |
| `waiting_for_input` | The workflow, when the agent calls `request_user_input`. It waits 30 minutes for an answer. |
| `waiting_for_continuation` | The workflow, on the iteration limit or the budget ceiling. It waits up to 24 hours. |
| `completed` | The workflow, as soon as the completion gate passes — not at workflow exit. |
| `failed` | The workflow, on an unsuccessful termination or an unhandled error. |
| `blocked` | The workflow, when a required capability is unavailable. |
| `cancelled` | `TemporalTaskManager.cancel_task`. |
| `working` | Nothing. It is accepted by validation and mapped for A2A, but no code path writes it. |

A twelfth value, `routed`, is returned to the caller but never stored. When a
channel message carries a `chat_id` that matches a live workflow for the same
agent, the message is signalled into that workflow and the existing task comes
back marked `routed` — no new task is created and no new policy is resolved.

### Terminal states depend on which surface you ask

This is the part that trips people up, because the two answers differ.

**On the task row**, four states end it: `completed`, `failed`, `blocked`,
`cancelled`. `AgentTask.is_completed()` returns true for exactly these.

**On the event feed**, three types end it: `task.completed`, `task.failed`,
`task.cancelled`. There is no `task.blocked` event. A blocked task writes
`blocked` to its row and emits `task.failed` on the feed, because the workflow
picks the event type from `state.success` and blocked runs are not successful.
A consumer watching the stream sees a failure; a consumer reading the row sees
the more specific reason. `failure_reason` carries the machine-readable code in
both cases — `capability_unavailable`, `validation_failed`, `iteration_limit`,
`budget_exceeded`, `missing_final_response`, `task_unsuccessful`.

### Completion is gated, not asserted

An agent does not finish by saying it finished. When it calls the completion
tool, the workflow runs an artifact validation activity against the committed
task workspace and branches on the result:

- **passed** — the task succeeds, the row is written `completed` immediately,
  and the final response is stored.
- **failed** — the agent gets structured repair feedback as a tool result and
  tries again. After two repair attempts the task ends `failed` with
  `failure_reason: validation_failed`.
- **unavailable** — the validator itself could not run. The task ends `blocked`
  with `failure_reason: capability_unavailable`. It does not fall through to
  success.

### `completed` does not mean the workflow exited

After the gate passes, the workflow sets the row to `completed` and then stays
alive for 30 minutes waiting for a follow-up message. A follow-up clears the
terminal state, returns the row to `running`, and continues the same
conversation in the same workflow. Only delegation children skip this — their
parent is blocked awaiting their result, so sitting in a wait would deadlock it.

This is why a live Temporal status of `running` is never allowed to overwrite a
persisted `completed`: the workflow is legitimately alive after the task is
done.

### Continuation

Hitting the iteration limit or the budget ceiling is not a failure yet. The
workflow records the reason, writes `waiting_for_continuation`, emits
`task.awaiting_continuation`, and idles for up to 24 hours.
`POST /v1/tasks/{task_id}/continue` grants more iterations, more budget, or
both, as a Temporal update that returns whether the grant was accepted. The
grant must match the reason: additional iterations for `iteration_limit`,
additional budget for `budget_exceeded`. A mismatched or late grant returns 409.
If the window expires, the task ends `failed`.

## Why not derive status from Temporal

The obvious simplification is to delete the status column and ask Temporal.
AgentArea does not, for three reasons.

Temporal's status vocabulary is coarse — running, completed, failed, cancelled —
and cannot express `blocked`, `waiting_for_input`, or
`waiting_for_continuation`, which are the states users actually need to act on.
Temporal's retention is bounded, so history older than the retention window
stops answering. And a workflow status cannot be joined against a
workspace-scoped SQL query, which is what every list view and every audit
question needs.

The cost of keeping both is a reconciliation rule, and AgentArea states it
explicitly: the database is the source of truth, and Temporal is consulted only
as a recovery oracle for terminal states. `_enrich_task_with_workflow_status`
upgrades a stale row when Temporal reports a terminal status and ignores
Temporal otherwise.

## Limits

- **Cancel does not write the row.** `DELETE /v1/agents/{agent_id}/tasks/{task_id}`
  cancels the Temporal workflow and returns. It does not persist `cancelled`.
  `GET /v1/agents/{agent_id}/tasks/{task_id}` enriches from Temporal and will
  report `cancelled`; the list endpoint does not enrich, so a cancelled task can
  still read `running` in a list view and in the database.
- **There is no wall-clock timeout on a task.** `AgentExecutionRequest` carries
  an optional `timeout_seconds` field and the workflow never reads it. The only
  termination conditions are goal achieved, iteration limit, and budget
  exceeded. A task that keeps making progress runs until one of those trips.
- **Transitions are unvalidated.** Validation checks that a status is a member
  of the allowed set, not that the move from the previous status is legal. Any
  status can follow any other.
- **The iteration budget has no runtime fallback.** The resolved governance
  snapshot must provide `execution.max_model_turns`. A typed
  `execution.max_model_turns` request may tighten that ceiling and is persisted
  into the task policy; missing execution policy rejects the run.
- **Two tasks are not isolated from each other's spend.** The month-to-date cap
  is checked once at creation. A task already running is not stopped when the
  workspace crosses the cap; only new task creation is refused.

## Related

- [Durable execution](/concepts/execution/durable-execution) — what Temporal
  contributes to the states above, and what it costs.
- [Events](/concepts/execution/events) — the feed those terminal types end.
- [Artifacts](/concepts/execution/artifacts) — what the completion gate
  validates.
