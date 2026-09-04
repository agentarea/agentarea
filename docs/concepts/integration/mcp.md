---
title: MCP
type: concept
summary: What the Model Context Protocol gives an agent, and how AgentArea hosts MCP servers — managed containers versus remote endpoints — behind one governed proxy.
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/integration/registry-and-catalog
  - /concepts/integration/bundles
  - /concepts/governance/tool-authorization
  - /concepts/execution/durable-execution
last_updated: 2026-07-29
---

# MCP

The Model Context Protocol is an open standard for exposing tools to a language
model. A server advertises tools with JSON schemas; a client discovers them and
calls them. AgentArea's contribution is not the protocol — it is hosting the
servers, holding their credentials, authorizing every call, and giving each one
a stable governed endpoint.

## The problem

A useful agent needs to reach GitHub, a database, a search index, a payments
API. Each of those integrations is third-party code or a third-party endpoint,
and each needs a credential.

Wire them directly and three problems arrive together. The credential has to
reach whatever process makes the call, which means it reaches the agent's
execution context. There is no single place that can say "this agent may not
call `delete_repository`", so authorization is per-integration and inconsistent.
And a server that stops responding fails at tool-call time, deep inside a task,
where the only signal the user gets is a confused agent.

## How AgentArea approaches it

### Two records: spec and instance

`MCPServer` is the **spec** — what a server is. Name, slug, version, tags,
`env_schema` describing the inputs it needs, the raw registry `json_spec`, and
exactly one transport field: `remote_url`, `cmd`, or `docker_image_url`. It may
carry `registry_item_id` and `registry_url` recording where it came from.

`MCPServerInstance` is the **runtime** — one configured, credentialed copy in
one workspace. It points at a spec via `server_spec_id`, carries its own
`json_spec` (type, environment or headers, resolved `internal_url`), a
`verification` record, the discovered `tools`, a `network_scope`, an optional
`auth_config_id`, and `last_used_at`.

### Three hosting shapes

| `type` | What runs | Endpoint |
|---|---|---|
| `url` | Nothing. The server is somebody else's. | The declared remote URL |
| `docker` | An image, provisioned by the Go MCP manager | `http://mcp-{instance_id}:{port}`, default port 8000, or the manager-reported `internal_url` |
| `command` | An npm/PyPI package wrapped in `agentarea/mcp-bridge:latest` | `http://mcp-{instance_id}:8080` |

Managed means `docker` or `command`: AgentArea runs the workload. Remote means
`url`: AgentArea holds the credential and governs the call, but the server is
operated by someone else.

### Provisioning is a synchronous call, not an event

For a managed instance, `verify()` in the Python service `POST`s `/instances` to
the Go MCP manager and takes the acknowledgement. The manager creates the
workload and reports the address it provisioned, which is persisted back into
`json_spec.internal_url` so the endpoint is not guessed from a naming
convention.

The Go manager still subscribes to `agentarea.events.mcp.instance.created`, and
deliberately ignores it — acting on the event would race the HTTP path and leave
orphaned config and secrets behind. Provisioning has one owner.

### Liveness is verification, not a status column

There is no `status` column on an instance. Liveness is
`verification.status`, one of `never_attempted`, `in_progress`, `succeeded`,
`failed`, plus a timestamp and a structured error.

Verification is an end-to-end trial run, and its success criterion is the
protocol's own: `tools/list` answered. It takes a row-level lock so a monitor
sweep and a user clicking Verify do not both re-run the expensive path, marks
`in_progress`, releases the lock, and then does the slow work.

For managed instances it polls `tools/list` every 5 seconds with a 5-second
per-attempt timeout, backstopped at 600 seconds. It does not fail on the clock
while the container is alive — a cold `uvx` or `npx` install can legitimately
take minutes — it fails early only when the manager's health endpoint reports
the container in `error`. A `succeeded` verification stores the discovered tool
list on the row as its receipt.

For remote instances there is no provisioning step; verification goes straight
to `tools/list`. Transport selection honours what the registry declared:
`remotes[].type` of `streamable-http` or `sse` is used exactly, with no probing
and no cross-transport fallback. Only for a hand-entered URL, where the
transport is unknown, does it fall back to suffix heuristics — a `/sse` suffix
means SSE only, a `/mcp` suffix means streamable-HTTP with a sibling `/sse`
fallback, and a bare URL tries the URL, then `/mcp`, then `/sse`.

A background monitor sweeps every 30 seconds. It marks any `in_progress`
verification older than 12 minutes as `failed` with
`code: verification_interrupted` — that threshold has to exceed the 600-second
safety deadline so it reaps only rows orphaned by a crashed worker — and
enqueues verification for managed rows still at `never_attempted`, five at a
time.

### One governed endpoint

Every instance is reachable at `/v1/mcp/{instance_id}/mcp`. The proxy:

- resolves the instance and its upstream URL,
- strips the caller's `Authorization` header and injects the instance's own
  outbound credential (OAuth bearer with automatic refresh, API key, or
  configured headers),
- runs each JSON-RPC `tools/call` through the same policy decision point the
  agent loop uses, resolving the workspace and user policy at request time,
- stamps `last_used_at` so the control plane can tell an idle instance from a
  busy one.

Downstream servers see only governed traffic, and the credential never leaves
the platform.

### Lazy provisioning

Instances can be started on demand. `needs_lazy_provisioning` is the single
predicate — the feature flag `MCP_LAZY_PROVISIONING_ENABLED` is on, the instance
declares `json_spec.lazy_provisioning`, and its verification is not `succeeded`.
Both callers that dispatch to an instance, the agent tool path and the proxy,
ask that one function, so they cannot disagree about when a server needs
bringing back up.

### Aggregating several servers

`MCPAggregatorProxy` merges the tools of several instances behind one FastMCP
endpoint, namespacing each tool as `{namespace}__{tool}` and forwarding calls to
the owning member. It is what lets a registered client — a Codex or Claude
harness — connect to a single endpoint and see a curated set of tools drawn from
several servers.

## Why not run MCP servers in the platform process

MCP servers are arbitrary third-party code in arbitrary runtimes: OCI images,
npm packages, PyPI packages. Importing that into the API process means a
dependency conflict is an outage, a crash takes the platform with it, and one
tenant's server shares an address space with another tenant's credentials.
Separating the control plane (the Go manager) from the workloads costs a network
hop and an extra moving part, and buys a blast radius of one container.

## Why not let agents call remote MCP endpoints directly

The direct path is genuinely simpler for `url`-type servers — no proxy, no
credential injection, one fewer hop. It gives up the three things that make the
integration governable. Authorization becomes per-server and unenforceable,
because the decision point is wherever the agent runs. The credential has to
reach the agent's context to be sent. And rotating a token becomes N problems
instead of one, because every agent configuration holds a copy.

## Why verification instead of a status column

A status column is a second copy of a fact the protocol can answer directly, and
a second copy is a thing that goes stale. "Did `tools/list` succeed, when, and
with what error" is one field written by one code path, and it carries its own
receipt: the tool list it discovered. A status column would need a writer for
every transition, and every writer is a place the two can diverge.

The cost is that liveness is only as fresh as the last verification. See the
limits.

## Limits

- **`succeeded` is a past-tense fact.** Nothing re-verifies a healthy instance on
  a schedule. The monitor sweep only picks up rows at `never_attempted` and
  reaps stale `in_progress` rows. A server that goes down after succeeding keeps
  reading `succeeded` until something re-verifies it.
- **The tool list is a snapshot.** Tools discovered at verification are stored on
  the row. A server that adds a tool later is not rediscovered until a
  re-verification or an explicit
  `POST /v1/mcp-server-instances/{instance_id}/discover-tools`.
- **The proxy is Streamable HTTP only.** An SSE-only server can be verified —
  verification falls back to SSE — but it cannot be served through
  `/v1/mcp/{instance_id}/mcp`.
- **`compound` and `bundle` instance types are not proxied.** The per-instance
  proxy dispatches `url`, `docker`, and `command`. Aggregation is a separate
  endpoint.
- **An interrupted verification blocks re-verification for 600 seconds** unless
  the caller forces it, which is what the user-initiated Verify action does.
- **Governance at the proxy has no task context.** The proxy resolves workspace
  and user policy at request time. A task-scoped policy tightening, which exists
  when the same tool is called from inside a task, is not available on this path.
- **Isolation is the container's.** AgentArea scopes credentials and authorizes
  calls; it does not constrain what a remote server does with a credential once
  the call is made, and a managed container's isolation is whatever the
  substrate provides.

## Related

- [Registry and catalog](/concepts/integration/registry-and-catalog) — where MCP
  server specs come from.
- [Bundles](/concepts/integration/bundles) — installing servers, skills, and
  agents together.
