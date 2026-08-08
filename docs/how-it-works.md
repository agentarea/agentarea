---
title: How it works
type: concept
summary: Follow one task from an API call to a finished result, and learn what each of the four AgentArea services is responsible for.
prerequisites:
  - /
related:
  - /concepts/control-and-data-plane
  - /concepts/execution/durable-execution
  - /concepts/workspaces-projects-resources
  - /concepts/governance/policy-engine
last_updated: 2026-07-29
---

# How it works

AgentArea runs as four processes: an API, a Temporal worker, a Go manager for
sandboxes and MCP servers, and a web dashboard. Most confusion about the platform
comes from not knowing which of them does what, so this page follows a single
task across all four.

Read this before the rest of the documentation. Nearly every other page assumes
you know where the thing it describes runs.

## The problem

An agent task is not one operation. It is a policy decision, a durable
orchestration, a series of model calls, and some number of commands executed in
an isolated environment — potentially over hours, with a human approval in the
middle.

Put that in one process and you get a system where a deploy kills in-flight work,
untrusted model output executes next to your database credentials, and an
approval means holding an HTTP connection open until someone gets back from
lunch. The four-process split is what avoids each of those, and each boundary
costs something.

## The four processes

| Process | Language | Responsible for |
|---|---|---|
| API (`apps/api`) | Python, FastAPI | Authentication, authorization, CRUD, policy resolution, event streaming to clients |
| Worker (`apps/worker`) | Python, Temporal SDK | Running agent workflows: the reason-act loop, model calls, tool calls |
| MCP manager | Go | Sandbox sessions, MCP server instances, container lifecycle on Kubernetes or Docker |
| Dashboard | Next.js | The web interface |

Backed by PostgreSQL (state), Valkey (streams and cache), object storage
(artifacts and logs), Temporal (workflow history), and OpenFGA or Ory Keto
(authorization).

The API and worker are the control plane. The MCP manager and everything it
starts are the data plane. See
[control plane and data plane](/concepts/control-and-data-plane) for why that
boundary is drawn where it is.

## The path a request takes

Starting a task: `POST /v1/agents/{agent_id}/tasks/`.

### 1. The API authenticates and scopes

The token is resolved into a `UserContext` carrying `user_id`, `workspace_id`,
and `accessible_workspaces`. Every repository is constructed from this context,
so reads are constrained to workspaces the caller can access before any handler
logic runs.

### 2. The API resolves an effective policy

Before the task starts, the governance layer resolves the policy that will apply
to it — budgets, which tools are permitted, what requires approval. The result is
attached to the task and handed to the workflow.

This is a snapshot taken at creation. The running workflow carries the effective
policy in its state and is the canonical source for it, which means editing a
policy does not retroactively change a task already in flight.

### 3. The API hands off to Temporal

`TaskService` persists the task, then `TemporalTaskManager` starts an
`AgentExecutionWorkflow`. The API returns immediately with a task id. It does not
wait for the agent.

For local development, `WORKFLOW__EXECUTION_ENGINE=direct` swaps in
`DirectTaskManager`, which runs the same logic in-process with no Temporal. Same
interface, no durability. Production uses Temporal.

### 4. The worker runs the agent loop

A worker picks up the workflow and runs the reason-act loop: build context, call
the model, get back either a final answer or tool calls, execute them, feed
results back, repeat.

Each model call and each tool call passes the governance interceptor pipeline
first. Budget gates run earliest because they are the cheapest check, then
security filters, then observers. A gate can deny the call or escalate it for
human approval.

Progress is published as events, which the API relays to clients over
server-sent events (`text/event-stream`), and persisted to the database. The
dashboard's live view is that stream.

### 5. Tool calls reach the data plane

A tool call is one of two things.

**An MCP tool call** goes to an MCP server instance — hosted by AgentArea in a
container the Go manager started, or a remote server. Secrets are resolved
server-side; the agent never sees them.

**A shell or skill execution** goes to the sandbox. The client posts to
`POST /sandbox/executions` on the Go manager, which persists a pending record and
publishes a request event. A runner claims it from a Valkey Streams consumer
group, executes it, writes logs and artifacts to object storage, and reports
lifecycle events back. The workflow reads completion from the execution record.

Output does not come back inline. Artifacts and logs are referenced by handle, so
large payloads never enter workflow history.

### 6. The task reaches a terminal state

The workflow completes, fails, or is cancelled. Final state is persisted, a
terminal event is published, and artifacts remain in object storage addressed by
their content hash.

## What Temporal is doing

Temporal gives the agent loop durability that a plain async function cannot have.

**It persists progress, not only results.** Every completed activity — a model
call, a tool call — is recorded in workflow history. If the worker crashes or you
deploy mid-task, a new worker replays history and resumes from where it stopped.
Completed work is not repeated.

**It lets a workflow wait without holding anything open.** This is what makes
human approval practical. When a tool call escalates, the workflow suspends. No
connection is held, no thread blocked, no timeout to tune. Approval arrives later
as a signal:

| Signal | Effect |
|---|---|
| `pause_execution` | Suspend the run |
| `resume_execution` | Continue it |
| `resolve_escalation` | Approve or deny a specific escalated tool call |
| `handle_a2ui_action` | Deliver a user interaction from the dashboard |
| `workflow_command` | Mid-run control, such as changing the model |

**It exposes live state without a database round trip.** Queries —
`get_current_state`, `get_workflow_events`, `get_latest_events` — read from the
running workflow directly.

**It handles retries.** Activities carry retry policies, so a transient provider
error is retried by the platform rather than by code in the agent loop.

The constraint this buys is real: workflow code must be deterministic. It cannot
call the network, read a clock, or generate randomness directly — all of that
belongs in activities. That rule is why the workflow file is structured the way
it is, and why side effects live in activities even when inlining would be
shorter.

## What the Go MCP manager is doing

The Go service manages everything that runs in a container. It exists as a
separate process in a different language because container orchestration is a
poor fit for the Python async model, and because it is the piece that must be
replaceable to support customer-hosted execution.

It exposes four route groups:

| Routes | Purpose |
|---|---|
| `/instances` | MCP server instance lifecycle: create, update, delete, validate, health |
| `/sandbox/executions` | Create an execution, read its state, apply lifecycle events |
| `/sandbox/files` | Push files into a sandbox and read them back |
| `/containers` | Lower-level container lifecycle |

It runs against Kubernetes or Docker, selected by `BACKEND_TYPE`. An unrecognised
value is refused at startup rather than falling back to a guess — a silent
fallback here previously meant deployments that set `BACKEND_TYPE: kubernetes`
ran on whatever auto-detection picked.

MCP server instances and agent sandboxes run on the same isolated substrate, so
one set of isolation and lifecycle behaviour covers both.

## Why not one process?

A single process is easier to run and easier to reason about, and for a
single-user local setup it would be enough.

It fails on three specific things. Untrusted code execution would share an
address space with credentials and the database connection. A deploy would kill
in-flight tasks, because durability requires state to live outside the process
doing the work. And the control/data split would be impossible, so
customer-hosted execution — the requirement that makes the platform usable by
regulated organizations — could not exist.

The cost of splitting is paid in debugging: a failed task can fail in any of four
places, and correlating them means following a task id across the API log, the
workflow history, and a runner log.

## Why not call the sandbox synchronously?

Because agent commands outlive HTTP connections, because returning stdout inline
pulls payload through the control plane the boundary exists to protect, and
because addressing a runner directly requires the control plane to know a URL —
which forecloses a customer-hosted runner that connects outbound. A synchronous
path exists for the managed Kubernetes warm pool as a compatibility route; it is
not the production contract.

## Limits

- **Policy is snapshotted at task creation.** Editing a policy does not affect
  tasks already running. If you need an immediate change to take effect, cancel
  the in-flight tasks.
- **`WORKFLOW__EXECUTION_ENGINE=direct` has no durability.** It is for
  development. A crash loses the task, and nothing resumes.
- **Determinism constrains workflow code.** Non-deterministic calls in workflow
  code produce replay failures that surface later, on the resume path, not when
  the code is written.
- **Event delivery over SSE is not guaranteed.** Events are persisted to the
  database as well; treat the stream as a live view, and the database as the
  record. A client that disconnects should reconcile rather than assume it saw
  everything.
- **The four processes must be version-compatible.** They are deployed together
  and share schemas. Upgrading the API without the worker is not supported.
- **A task id is the only correlation handle across services.** There is no
  single log stream that shows the whole path.

## Related

- [Control plane and data plane](/concepts/control-and-data-plane) — the boundary this path crosses
- [Durable execution](/concepts/execution/durable-execution) — Temporal in depth
- [Workspaces, projects, and resources](/concepts/workspaces-projects-resources) — the scoping applied in step 1
- [Policy engine](/concepts/governance/policy-engine) — how the effective policy in step 2 is resolved
