---
title: Sandbox sessions
type: concept
summary: A sandbox belongs to a task rather than to a command, so successive commands see the same filesystem and processes; this page covers how a session is assigned, kept alive, and retired.
prerequisites:
  - /concepts/sandbox/why-a-sandbox
  - /concepts/execution/tasks
related:
  - /concepts/sandbox/lifecycle
  - /concepts/sandbox/the-file-model
  - /concepts/sandbox/isolation
  - /concepts/execution/durable-execution
last_updated: 2026-07-29
---

# Sandbox sessions

A sandbox session is one execution environment bound to one task. Every command
that task runs lands in the same place, against the same filesystem, until the
task ends. An agent that writes a file in one step and reads it back in the next
is relying on the session, and the session is what makes that work.

The alternative — a fresh container per command — is what the platform used
before, and it does not survive contact with how agents actually work.

## The problem

An agent works in steps. It writes a script, runs it, reads the traceback, edits
the script, runs it again. Each of those is a separate decision by the model,
separated by a round trip to an LLM that may take seconds.

If each command runs in a new container, none of that composes. The script the
agent wrote in step one does not exist in step two. Installed packages vanish.
A half-finished build starts over. The agent's workaround is to reconstruct its
world on every call — writing the file again, reinstalling the dependency — which
inflates every command, and is the kind of thing models do inconsistently.

The opposite failure is equally real. One long-lived sandbox shared across tasks
means task A's leftover files, environment, and processes are visible to task B.
That is a data leak between tenants of the same workspace and a source of
irreproducible behaviour.

The session model sits between: an environment that lives exactly as long as the
work it belongs to.

## How AgentArea approaches it

**One sandbox per task, found by task identity.** The manager locates a task's
sandbox by a label carrying the task ID. If a pod already carries that label, it
is the session; if none does, one is allocated from the warm pool, or created
from a template when the pool has nothing free. There is no per-call
provisioning, and no way for two concurrent commands on one task to reach
different sandboxes.

**Commands execute in place.** Rather than starting a container, the manager
posts the command to an executor already running inside the task's pod, on port
8080. The command runs against the live filesystem of a pod that is already up,
which is why the working directory persists across steps.

**The data plane is selected by the deployment, not by the task.** Python sends
only workspace and task identity plus the requested operation. The Go manager
selects the configured Kubernetes, OpenSandbox, E2B, or compatible provider and
pins the resulting provider session to that identity. Runtime image, package
availability, network access, and isolation requirements are operator policy;
there is no task-level `allowed`/`locked` switch and no weaker fallback.

**Leases keep active work alive and reclaim idle sessions.** Every command and
file operation renews the deployment-configured active lease, and long commands
heartbeat it while they run. Once an operation reaches quiescence, the Go
manager changes the binding to its configured idle lease. The next HTTP request
rehydrates or renews the same task workspace; an expired provider session is
recreated on demand. Python and Temporal do not schedule sandbox cleanup.

### The lifecycle of a session

A provider session moves through a manager-owned request lifecycle:

| Stage | What happens | What ends it |
|---|---|---|
| Demand | An HTTP file or command request reaches the manager | A matching binding is found or provisioned |
| Active | The operation runs and renews the active lease; commands heartbeat it | The operation reaches quiescence |
| Idle | The manager renews the binding to `SANDBOX_TASK_IDLE_TTL` | Another request reactivates it, or the lease expires |
| Reclaimed | The provider releases the compute session | New demand provisions a replacement and rehydrates durable state |

The durable task workspace and published artifacts are separate from compute
retirement. Reclaiming a provider session must not make one task's files visible
to another, and the next session materializes only that workspace's manifest.

### Execution is a durable record, not an HTTP call

A command is not a synchronous request that a workflow waits on. Creating an
execution persists a record and publishes a CloudEvent onto a Redis stream. A
runner consumes that stream through a consumer group, claims the execution, runs
it, and publishes lifecycle events back. The execution record carries a status
drawn from `queued`, `claimed`, `running`, `completed`, `failed`, and
`cancelled`.

The runner acknowledges the request message only after the terminal state is
stored. If a runner dies mid-execution, the message is redelivered rather than
lost.

This is also why command bodies and results are constrained. The execution API
rejects inline `args`, `env`, `script`, `input_files`, and `content_base64`
outright, and refuses to persist a result carrying inline `stdout` or `stderr` —
those must be references to stored objects. Large payloads stay out of workflow
history and out of control-plane events.

### Where a session may run

Placement chooses a data plane per execution, matching the execution's declared
region against registered targets. An execution constrained to a region runs on a
target in that region or does not run at all; there is no fallback to a target
that declares no region. Nothing is placed on a non-matching target.

Because there is no per-task pin to a target yet, the placement registry refuses
to start with two targets in the same region — with "first eligible" selection,
a duplicate region could re-route a task to a different sandbox mid-session and
leave its workspace behind.

## Why not one container per command

Statelessness is genuinely easier to operate. Nothing to reclaim, nothing to
leak between steps, no lease machinery, and a crash loses nothing because there
was nothing there.

It loses because the unit of work is wrong. An agent's step is not a program; it
is one move in a sequence that only makes sense against accumulated state.
Rebuilding that state per command means either paying container startup on every
tool call — several seconds against an agent that may make dozens — or pushing
the reconstruction into the model's prompt, where it is unreliable. Sessions move
the cost to once per task.

What the platform gives up is real: sandboxes are stateful, so they have to be
tracked, leased, and reclaimed, and a leak is a resident pod rather than a
process that already exited. The lease and the GC loop exist to pay that bill,
and the limits below are where the bill is not fully paid.

## Why not keep the sandbox alive across tasks

A per-workspace sandbox that never goes away would remove cold starts entirely
and let an agent build up a working environment over time.

It breaks isolation between tasks, which is the property the sandbox exists to
provide. Task A's files, environment variables, and background processes would be
readable by task B, and the file model's task-scoped prefixes would stop being
enforceable — they would still describe durable storage, but not what is on the
local disk. It also makes behaviour depend on execution history, so a task that
passes today fails tomorrow because something earlier left state behind.

## Limits

**A live task that goes quiet holds its sandbox for up to the full lease.** The
only things that release a sandbox are explicit retirement at the end of the task
and expiry of the lease. There is no idle reclaim for a task that is still open,
so an agent that stops issuing commands for twenty minutes — waiting on an
approval, or finished thinking — keeps its pod for as long as two hours by
default. This is capacity held, not a correctness problem, but on a small pool it
is capacity that is not available to other tasks.

**Nothing in the working directory survives the pod.** When the sandbox is
deleted, its filesystem goes with it. Files the agent wrote through the file tool
are written through to durable storage and survive; anything created only by a
shell command in the sandbox does not, unless it was collected as an artifact.
See [the file model](/concepts/sandbox/the-file-model) for which writes are
durable.

**Writeback must reach the same pod that ran the command.** Committing workspace
changes looks up the existing pod for the task rather than allocating one. If
that pod is already gone, the changes cannot be committed — a replacement pod
does not have them.

**Session assignment is not a scheduling guarantee.** Allocation falls back to
creating a pod from a template when the warm pool has nothing free. If the
cluster cannot schedule that pod, the task waits on ordinary Kubernetes
scheduling, and capacity exhaustion is not currently reported distinctly from
other provisioning failures.

**The teardown endpoint is authenticated by a single shared secret.**
`DELETE /sandbox/task/:id` requires a bearer token compared against
`SANDBOX_CLEANUP_AUTH_SECRET` in constant time. When that variable is unset every
request is rejected, so teardown stops rather than running unauthenticated —
but the pods it would have retired are then reclaimed only when their leases
expire.

## Related

- [Lifecycle](/concepts/sandbox/lifecycle) — warm pool, activation, and idle reclaim
- [The file model](/concepts/sandbox/the-file-model) — what persists and where
- [Isolation](/concepts/sandbox/isolation) — the boundary around a session
- [Tasks](/concepts/execution/tasks) — the unit a session is bound to
- [Durable execution](/concepts/execution/durable-execution) — how workflows wait
  on sandbox work
