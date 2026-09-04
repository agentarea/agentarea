---
title: Durable execution
type: concept
summary: What Temporal actually provides to an AgentArea task — replay, retries, signals, queries, durable timers — and the constraints you take on in exchange.
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/execution/events
  - /concepts/execution/artifacts
  - /concepts/governance/policy-engine
last_updated: 2026-07-29
---

# Durable execution

An agent run is a loop that calls a model, calls tools, and decides whether it
is done. AgentArea runs that loop as a Temporal workflow, which means the loop's
state survives the process executing it. If the worker is killed mid-iteration,
another worker picks the run up at the same point with the same conversation
history, the same budget counter, and the same pending approvals.

## The problem

An agent loop is long, expensive, and externally interactive. It can run for
minutes to hours, each iteration costs money that must not be spent twice, and
users need to pause it, approve a tool call, change its model, or send it a new
message while it runs.

Run that loop in a web process and every one of those breaks. A deploy kills it
with no record of where it was. A retry re-runs LLM calls already paid for.
There is no way to address a running loop from outside, so approval and
follow-up have to be faked with polling and a shared cache. And the failure mode
is silent: the user sees a spinner that never resolves.

## How AgentArea approaches it

`AgentExecutionWorkflow` is the loop. Everything with a side effect — calling
the model, calling a tool, writing task status, publishing events, materializing
skill files, validating artifacts — is a Temporal activity. The workflow itself
only decides and remembers.

The workflow id is `task-{task_id}` and the task queue is `agent-tasks`. That id
is deterministic, so any surface that knows the task id can address the running
workflow without a lookup.

### What replay buys

Temporal records every activity result in the workflow's history and replays
that history to rebuild in-memory state after a crash. The practical consequence
is that a completed LLM call is never re-issued: on replay, the workflow reads
the recorded result instead of calling the model again. The budget counter, the
message list, and the iteration number come back exactly as they were.

### Retries are per activity and typed

Each activity carries its own timeout and retry policy:

| Activity class | Timeout | Attempts |
|---|---|---|
| Most activities | 5 min | 3 |
| LLM call | 10 min | 3 |
| Tool execution | 35 min | 3 |
| Event publish | 5 s | 1 |
| Delegated child agent | 10 min | — |

Retries are not blanket. `make_retry_policy` derives Temporal's
`non_retryable_error_types` from the `PermanentError` class hierarchy, so an
activity that raises `AgentNotFoundError` or `ModelInstanceNotFoundError` fails
immediately rather than burning three attempts on a failure that cannot change.
Adding a permanent failure is a new subclass in the domain; the policy picks it
up with no change at the Temporal layer.

The LLM path draws the same line inside the provider taxonomy. Authentication
failures, quota exhaustion, and unknown-model errors are permanent. Rate limits
are explicitly not — a 429 is retried with backoff, and the check for it runs
before the quota check so that "rate limit exceeded" is not swallowed by a
substring match on "exceeded".

### Signals, updates, and queries

External control is not polling. Five signals reach a running workflow:

- `pause_execution` / `resume_execution` — the loop parks on a wait condition.
- `resolve_escalation` — approve or deny a specific tool escalation. The
  workflow re-checks the caller against the task's approver list and ignores an
  unauthorized signal, so the API boundary cannot bypass policy.
- `handle_a2ui_action` — a UI interaction, queued and injected as a user message.
- `workflow_command` — a dispatcher for `change_model`, `update_budget`,
  `continue_execution`, `queue_message`, `submit_user_input`, `remove_message`.

`continue_execution` also exists as a Temporal **update**, which is what the
continuation endpoint uses: a signal is fire-and-forget, and granting resources
needs a validated accept/reject answer in the response.

Three queries read state without touching it: `get_current_state`,
`get_workflow_events`, `get_latest_events`. `get_current_state` is how the
governance API serves the effective policy a task is actually running under —
the workflow carries the resolved snapshot, so the answer is the one being
enforced rather than a re-resolution that might differ.

### Durable timers

Waiting is free. The 30-minute follow-up window, the 30-minute user-input
window, and the 24-hour continuation window are all Temporal timers. The
workflow consumes no worker slot while parked; Temporal persists the state and
wakes it on signal or expiry. A task can sit in `waiting_for_continuation`
overnight at no runtime cost.

### Continue-as-new

Temporal history has a size limit, and a long agent run will reach it. When
`is_continue_as_new_suggested()` returns true, the workflow compacts its message
history, packs its state into a `ContinueAsNewState`, emits an event, and
restarts with a fresh history. The task id stays the same, so nothing outside
notices.

## Why not run the loop in the API process

That option exists in the codebase. Setting `WORKFLOW__EXECUTION_ENGINE=direct`
swaps in `DirectTaskManager`, which runs the loop in-process. It is a useful
comparison because it shows precisely what durability is worth.

`DirectTaskManager` runs the whole loop inside the submitting request, so the
caller blocks until the agent finishes. It has a hard-coded ceiling of 10
iterations. `cancel_task` logs a warning and returns `False`. It supports two
tools — skill activation and completion — and answers any other tool call with
"Unknown tool". It emits no workflow events, so nothing streams. A restart loses
the run with no record beyond a `failed` row.

## Why not a job queue

Celery, Arq, or a Redis work queue give you retry and at-least-once delivery,
which covers the crash case. They do not give you the other three.

There is no replayable history, so a retry re-runs the whole job including LLM
calls already paid for — you have to build your own checkpointing and make every
step idempotent. There is no addressable handle on a running job, so approval,
model change, and follow-up messages need a side channel and a polling loop.
And there are no durable timers, so a 24-hour wait is either a held worker or a
scheduled re-enqueue you have to write and monitor.

The honest version of the tradeoff: you can build this on a queue, and what you
end up with is a worse Temporal.

## Limits

- **Determinism constrains the workflow file.** Workflow code cannot read the
  clock, generate randomness, or perform I/O directly. Imports that touch those
  go through `workflow.unsafe.imports_passed_through`. Every side effect must be
  an activity, which is why the file is long and indirect.
- **There is no workflow versioning in use.** The codebase uses no
  `workflow.patched` or `get_version` calls. A change to workflow control flow
  can therefore break replay for in-flight workflows started against the older
  code. Deploys that change the loop should drain first.
- **`ContinueAsNewState` is a manual enumeration.** Every field of workflow
  state that must survive a continue-as-new is listed by hand. A new field added
  to the workflow and not added there is silently lost at the next restart.
- **The immediate event-publish path can drop events.**
  `_publish_events_immediately` clears its pending buffer before it publishes,
  with a 5-second timeout and a single attempt. If the publish activity fails,
  those events are gone from the workflow's buffer, and the failure surfaces as
  a workflow error rather than a retry.
- **Temporal orchestrates within a task, not between contexts.** Cross-context
  reactions — an agent deletion deactivating its triggers, for example — are the
  event bus's job, not the workflow's. Do not reach for a child workflow to do
  choreography.
- **Cancellation is a Temporal-side fact.** See the cancel limit in
  [Tasks](/concepts/execution/tasks#limits).
- **Operating this is real work.** A Temporal server, its datastore, and at
  least one worker are load-bearing infrastructure. If the worker fleet is down,
  tasks are created and never dispatched.

## Related

- [Tasks](/concepts/execution/tasks) — the states this machinery moves a task
  through.
- [Events](/concepts/execution/events) — how workflow progress reaches a client.
