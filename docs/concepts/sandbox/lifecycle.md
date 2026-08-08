---
title: Sandbox lifecycle
type: concept
summary: How sandboxes and MCP instances are brought up from a warm pool, activated, and reclaimed when idle — and which of those reclaim paths do not currently fire.
prerequisites:
  - /concepts/sandbox/sessions
related:
  - /concepts/sandbox/isolation
  - /concepts/sandbox/why-a-sandbox
  - /concepts/integration/mcp
  - /serverless-mcp
last_updated: 2026-07-29
---

# Sandbox lifecycle

Workloads on this platform are not meant to run continuously. A sandbox exists
while its task does; an MCP server can be started on first use and stopped once
nobody is calling it. This page covers how they come up, and how they go away.

Reclaim is a security property as much as a cost one. A workload that runs
forever is a workload whose compromise lasts forever.

## The problem

Starting a container on demand is slow in a way that agents feel. Pulling an
image, unpacking it, and starting a process takes seconds; an agent may make
dozens of tool calls in one task, and a user is watching. Paying that on every
call is not viable.

Never stopping anything is the other extreme, and it is what the platform did
originally. A workspace with thirty MCP connections ran thirty containers whether
or not an agent had called any of them that month. The cost is continuous, the
utilization is near zero, and each idle container is still a piece of
third-party code with a network connection.

The two workloads also differ in what stopping them costs, which is why they get
different treatment.

## How AgentArea approaches it

### The warm pool removes provisioning from the request path

Rather than creating a pod when work arrives, the platform keeps a set of pods
already running and unassigned. Assigning one is a label update, so the expensive
part — scheduling, image pull, container creation — happened before anyone was
waiting.

A pooled pod is not yet the workload it will become. It runs an activation
service listening on port 8080. Activating it posts the target image, and the
service fetches and extracts that image into an overlay directory, reads the
image config for its `ENTRYPOINT`, `CMD`, and `WORKDIR`, and starts the process
under `chroot` into the extracted root filesystem, so relative entrypoints behave
as they would under a container runtime.

Pods move through recorded states: `waiting`, `activating`, `ready`, `assigned`,
then `idle` once the work is over.

Activation endpoints are authorized with scoped tokens — separate scopes for
`activate`, `execute`, `writeback`, and `files` — signed by the control plane, so
a pod's executor cannot be driven by anything that has not been issued the right
scope.

**Runtime policy is deployment-owned.** The built-in Kubernetes provider may use
a warm pool, while external providers allocate their own sessions. In every
case, the Go manager chooses exactly one configured provider and runtime policy;
task payloads do not carry an image or package-install profile. If the selected
provider cannot attest the required isolation boundary, creation fails loudly.

### Sandboxes are reclaimed from observed HTTP activity

The Go manager is the lifecycle authority. A command or file request provisions
or reuses the task binding and renews its active lease; command heartbeats keep
that lease alive. When the operation finishes, the manager moves the binding to
`SANDBOX_TASK_IDLE_TTL`. A later request wakes or recreates it and materializes
the durable workspace. No Temporal activity names or invokes sandbox creation,
retirement, or cleanup, so switching data-plane providers does not change the
agent workflow.

### MCP instances can be serverless, because stopping them costs nothing

An MCP instance is stateless with respect to startup: it is an image plus
environment variables from the database. Stopping and restarting it returns the
same instance, so reclaiming it is lossless. That is why serverless is available
for MCP and not, currently, for sandboxes — a sandbox holds a working directory
that dies with the pod.

When serverless is on, an instance is started on its first call and stopped after
it goes idle. Only the workload goes; the database row, the credentials, and the
discovered tool list are untouched, and the next call provisions it again through
the path that started it the first time.

Reclaim works by sweep. Every `sweepInterval` (default 60s) the manager selects
instances that are lazily provisioned, currently provisioned, and have not been
called for longer than `idleTimeout` (default 10m). It stops each workload and
resets the instance's verification state so the next caller provisions it rather
than dispatching into nothing. That reset is a compare-and-set against
`succeeded`, so a verification that started concurrently wins instead of being
overwritten.

Sweeping is serialized across manager replicas with a Postgres advisory lock. If
a manager dies mid-sweep the lock goes with its connection; there is nothing to
clear by hand.

Two categories are deliberately excluded. Remote (`url`-type) connections have no
container to stop. Instances that have never been called are treated as new
rather than idle — reclaiming requires evidence of disuse, not absence of
evidence of use.

**The mode is recorded per instance at creation.** Turning serverless on later
does not retroactively shorten the life of existing connections, and turning it
off does not strand ones created serverless.

## Why not keep everything running

Always-on is predictable. No cold starts, no first-call latency, no question of
whether the wake path works, and verification failures surface when a user
creates the connection rather than when an agent first calls it.

The platform's position is that this does not survive multiplication. Utilization
of a typical MCP connection is very low, and the resident cost is paid
continuously by every workspace. The security argument is the stronger one: an
idle container is still attack surface with a network path, and reclaiming it
shrinks the window in which a compromised or vulnerable server is reachable.

The costs are real and are not defects to be fixed. The first call after an idle
period pays a cold start whose length depends entirely on the server — a small
published image starts quickly, while a `uvx` or `npx` server that clones and
installs on boot can take substantially longer, and the call waits rather than
failing. And because verification is what starts the container and lists its
tools, deferring the start defers the check: a bad image reference or a missing
environment variable surfaces on first use instead of in the connection form.
Serverless is off by default for these reasons.

## Why not scale to zero with a queue in front

The tidier design gives each MCP server a queue and a scaler, so requests buffer
while the workload comes up, and there is no user-visible failure mode at all.

It adds a broker per connection and moves failure from "the call was slow" to
"the call is somewhere in a queue", which is harder to reason about and harder to
attribute when an agent's tool call hangs. It also does not remove the cold start;
it hides it behind a component that now has to be operated and monitored. The
current design accepts the visible wait in exchange for one fewer moving part per
connection, on the reasoning that an agent tool call is already an operation
where a several-second wait is normal.

## Limits

**Reclaim does not observe agent traffic.** The idle sweep selects on
`last_used_at`, and that column is written in exactly one place: the HTTP proxy
path used by registered CLI harnesses. The agent tool-call path resolves the
instance URL and calls the container directly, then enqueues a usage record onto
an in-process queue. The consumer of that queue,
`_flush_last_dispatch_loop`, has no production caller anywhere in the tree, and
it writes a different column (`last_dispatch`) in any case. Two consequences,
both bad:

- An instance used only by agents keeps `last_used_at` as NULL, is excluded by
  the selection query, and **is never reclaimed** — the main scenario, in which
  nothing is freed.
- An instance called once through the proxy and thereafter only by agents has a
  timestamp that goes stale under live traffic, so the sweep can **stop an
  instance that is actively in use.**

A comment in the proxy describing it as the only component that observes MCP
traffic is inaccurate, and the existing serverless page inherited that error.

**A serverless instance may not be callable at all.** Verification is skipped
when a lazy instance is created, and the `tools` column is written only by
verification. Tool discovery has an escape hatch for exactly this case — a lazy
instance passes if it declared its tools in advance — but nothing populates
`json_spec.available_tools`: its only writer, `set_available_tools`, has no
callers. The tool list is therefore empty, the escape hatch does not trigger, the
agent is offered no tools from that instance, and it never makes the first call
that would wake it.

**Stopping races with waking.** The sweep selects, deletes, then resets state. A
caller that has already read the instance as provisioned can dispatch to a
Deployment deleted moments earlier and get an error with no retry. Each
reclamation under live traffic can cost a failed tool call.

**The reaper does not start if the database is not configured, and says so only
at warning level.** A manager without database credentials logs a warning and
continues without reclaiming anything.

**A live task's sandbox is not reclaimed when idle.** Only end-of-task teardown
and lease expiry release a sandbox. An agent holding an open task that does
nothing for twenty minutes keeps its pod for up to the full lease, two hours by
default.

**The warm pool is off by default.** `mcpManager.warmPool.enabled` is `false`,
and the pool also requires the `warm_pool` feature flag. Without it, sandbox
pods are created on demand and pay full provisioning, and the sandbox
NetworkPolicies described in [isolation](/concepts/sandbox/isolation) are not
rendered.

**Activation falls back to running without `chroot`.** If `chroot` fails — for
example without `CAP_SYS_CHROOT` — the activation service logs a warning and
starts the image's entrypoint directly in the pod's own filesystem, rather than
inside the extracted image root. The comment describes this as expected under a
VM-isolating runtime where the VM boundary substitutes, but the fallback fires on
any `chroot` failure, including one where no such boundary exists.

**Published activation timings are not reproducible from this repository.** The
existing warm pool and serverless pages quote several different figures for
activation and cold start, none citing where they were measured, and the chart
comments give a different range again. Treat them as illustrative and measure
your own deployment.

## Related

- [Sessions](/concepts/sandbox/sessions) — what a sandbox holds while it lives
- [Isolation](/concepts/sandbox/isolation) — what confines it
- [MCP](/concepts/integration/mcp) — what an MCP instance is
- [Serverless MCP instances](/serverless-mcp) — enabling and verifying the mode
