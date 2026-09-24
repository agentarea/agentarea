---
title: Agent-to-agent communication
type: concept
description: "One agent invoking another is delegation; A2A is the transport binding used when the target is outside your platform, and this page separates the two."
prerequisites:
  - /concepts/agents/what-is-an-agent
  - /concepts/execution/tasks
related:
  - /concepts/execution/events
  - /concepts/execution/durable-execution
  - /concepts/governance/tool-authorization
  - /concepts/agents/skills
last_updated: 2026-09-25
---

When one agent hands work to another, the concept is delegation. A2A — the
Agent2Agent protocol — is one *transport binding* for delegation, used when the
target agent is not on this platform. It is not the umbrella and it is not the
default.

This distinction is enforced in the code, not only in prose. The model is
offered a single `delegate_to_<agent>` tool per target agent, and a facade
chooses the transport behind it. Whether the call crosses a network is an
execution detail the model never sees.

## The problem

An agent that can only do what one model plus one tool list can do runs into a
ceiling quickly, and the obvious fix — let agents call agents — raises a
question the obvious answer gets wrong. If every agent-to-agent call speaks a
network protocol, then two agents in the same workspace, running on the same
worker, sharing the same database session, serialize their request to JSON-RPC,
open an HTTP connection to their own API, re-authenticate, and re-resolve the
workspace they never left. That is a lot of machinery to reach a function call.

But the opposite mistake is worse. If agent-to-agent calls are only ever
in-process, an agent can never reach anything it does not own, and the platform
becomes a closed world with no story for a partner's agent, a customer's agent,
or an agent behind someone else's firewall.

What is needed is one concept with two bindings, and a rule for picking.

## How AgentArea approaches it

### Delegation is the concept, A2A is a binding

`AgentToolFactory.create_tool` resolves the target agent and picks a binding,
then wraps it in a `DelegationTool` facade. The facade forwards `name`,
`description`, `get_schema` and `execute` straight through, and carries a
`binding_kind` of `"local"` or `"a2a"` for observability only.

The rule is:

| Condition | Binding |
|---|---|
| The tool config sets `settings.a2a_url` | `a2a` — remote target, HTTP |
| No `a2a_url`, and a task service plus workspace and user context are present | `local` — direct task-service call |
| No `a2a_url` and no execution context | `a2a` against this platform's own endpoint, logged as a warning |

The third row is a fallback, not a design goal. It logs that `task_service`
should have been passed so a same-platform agent would use the local binding.

The tool name is derived from the target agent's name, sanitized to
`delegate_to_<name>`, and both bindings produce the same one-parameter schema: a
`message` string.

### The local binding

`AgentDelegationTool` builds an `AgentTask` addressed to the target agent id and
submits it through the task service — no HTTP, no auth round-trip. The task
carries `metadata: {"source": "agent_delegation", "delegated": true}`, which is
how a delegated run is distinguished downstream.

It then polls `get_task_with_workflow_status` every 2 seconds until the task
reaches `completed`, `failed` or `cancelled`. The ceiling is 600 seconds by
default, configurable through `AGENT_DELEGATION_POLL_TIMEOUT`. That number was
raised deliberately: a delegated task is a full agent run, and a research
sub-agent making web calls can legitimately need minutes, so a shorter ceiling
abandoned sub-agents that were still working.

Delegated children are also the one case that skips the post-completion wait
described in [Tasks](/concepts/execution/tasks) — their parent is blocked
awaiting the result, so idling would deadlock it.

### A2A is a transport over the same tasks

The important architectural claim about A2A here is that it is not a parallel
execution system. It is another way in to the task and event system that already
serves REST and messaging channels. `SendMessage` converts the A2A message to an
`AgentTask` and submits it through the same `TaskService`, so it gets the same
Temporal workflow, the same policy resolution, the same event stream and the
same artifacts as a task started from the UI.

The endpoint is a single JSON-RPC 2.0 route per agent:

```http
POST /v1/agents/{agent_id}/a2a/rpc
```

The protocol itself is not ours. The route authenticates the caller, then hands
the request to the official `a2a-sdk` JSON-RPC dispatcher, which owns the wire
types, method dispatch, error codes, SSE framing and the version check.
AgentArea supplies only a request handler that maps each typed call onto the
task service, the task event feed and push-config storage. Eleven methods are
served: `SendMessage`, `SendStreamingMessage`, `GetTask`, `CancelTask`,
`SubscribeToTask`, `ListTasks`, the four `*TaskPushNotificationConfig` methods,
and `GetExtendedAgentCard`. Every task method answers only for tasks that belong
to the agent in the URL; another agent's task is `TaskNotFoundError`.

### Sending is non-blocking, and that is deliberate

`SendMessage` returns as soon as the task is submitted, with a `Task` object
that is typically still in a non-terminal state, whatever the request's
`configuration.returnImmediately` says. The spec's default is to block until
the task is terminal or interrupted; AgentArea deliberately does not.
Forcing the HTTP request to block until the agent finished would time out behind
proxies and load balancers — the failure mode the design is avoiding.

The consequence is that the result arrives through a *retrieval* path, of which
there are three:

- **Polling** `GetTask` until the state is terminal.
- **Streaming** via `SendStreamingMessage` or `SubscribeToTask`, over SSE.
- **Push**, via a registered webhook.

### How a result reaches the wire

One helper builds the A2A `Task` for every non-streaming response, so `GetTask`,
`SendMessage`, `CancelTask`, `ListTasks` and delegation cannot disagree.

The canonical final answer is `task.result["response"]`, produced by the
workflow's `state.final_response`. On terminal success it is emitted twice: as
an `Artifact` containing a text part, and mirrored into `status.message` with
role `ROLE_AGENT`. The duplication is intentional — a spec-minimal client that only
reads `status.message` still gets the answer. On failure, `error_message` goes
into `status.message`.

Streaming maps the real workflow event stream onto the v1.0.0 `StreamResponse`
union, one of `task`, `statusUpdate` or `artifactUpdate` per frame. The first
frame is always the `task`. Incremental LLM output becomes an `artifactUpdate`
with `append: true`; a terminal event becomes a final `artifactUpdate` with
`lastChunk: true` followed by a `statusUpdate` carrying the terminal state. Any
other workflow event becomes a `TASK_STATE_WORKING` status update.
`SubscribeToTask` on a task that is already terminal is refused with
`UnsupportedOperationError`, as the spec requires; read it with `GetTask`.

Task row statuses map onto A2A states as follows: `submitted`, `pending`,
`preparing` and `scheduled` are `TASK_STATE_SUBMITTED`; `running` and `working`
are `TASK_STATE_WORKING`; the three `waiting_for_*` statuses are
`TASK_STATE_INPUT_REQUIRED`; `blocked` and `failed` are `TASK_STATE_FAILED`;
`cancelled` is `TASK_STATE_CANCELED`.

### Push notifications ride the channel pipeline

A registered webhook is modelled as an outbound channel of type `a2a_webhook`
and delivered through the same durable pipeline that delivers Telegram and Slack
messages, rather than through a second delivery mechanism.

Storage follows the channel precedent exactly: the non-secret part of the config
lives in `task_parameters["a2a_push_configs"]`, and the client's token goes to
the secret store under `a2a_push_token:<task_id>:<config_id>`, so it is never
echoed back by `get` or `list`. Delivery POSTs the full v1.0.0 `statusUpdate`
payload as a `StreamResponse` — the client gets the result without a
follow-up `GetTask` — and echoes
the token in an `X-A2A-Notification-Token` header so the client can authenticate
the callback. The URL is validated against the shared SSRF guard both when the
config is registered and again before each send.

Push is deliberately not a firehose: only terminal results and terminal status
are pushed, never incremental chunks.

### Protocol version

AgentArea speaks A2A v1.0 exactly as the official SDK encodes it — the SDK's
protobuf types are the wire types, serialized with the proto JSON mapping, so
any v1 client parses our responses without a shim. v0.3 compatibility is not
enabled. The wire details that matter:

- Methods are PascalCase RPC names, not slash-style (`SendMessage`, not
  `message/send`).
- There are no `kind` discriminators on `Task`, `Message`, `Part` or stream
  events.
- `Part` is flat: a part has `text`, or `data`, or `raw`/`url` with `mediaType`.
- `Message.role` is `ROLE_USER` or `ROLE_AGENT`, and `messageId` is required.
- `TaskState` values carry the enum prefix: `TASK_STATE_SUBMITTED`,
  `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`,
  `TASK_STATE_CANCELED`, `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_REJECTED`,
  `TASK_STATE_AUTH_REQUIRED`.
- `Artifact` has no `index`, `append` or `lastChunk`; `append` and `lastChunk`
  live on the streaming `artifactUpdate` event. Streaming frames carry no
  `final` boolean; terminal is conveyed by the state.
- The agent card advertises transports through `supportedInterfaces[]`, with no
  top-level `url` or `preferredTransport`, and bearer auth as
  `securitySchemes: {"bearer": {"httpAuthSecurityScheme": {"scheme": "bearer"}}}`
  with `securityRequirements: [{"schemes": {"bearer": {}}}]`.

The `A2A-Version` header is required. The spec reads a missing header as `0.3`,
so a request without `A2A-Version: 1.0` is refused with `-32009
VersionNotSupportedError`; the official clients always send it.

Existing v0.3.0 callers break by design, and so do callers of the pre-SDK
AgentArea dialect, which emitted bare `USER`/`COMPLETED` enums and a v0.3-shaped
card that the official SDK could not parse.

### Discovery

Four unauthenticated endpoints describe an agent:

| Endpoint | Returns |
|---|---|
| `GET /v1/agents/{agent_id}/.well-known/agent-card.json` | The A2A agent card |
| `GET /v1/agents/{agent_id}/.well-known/a2a-info.json` | Protocol and endpoint metadata |
| `GET /v1/agents/{agent_id}/.well-known/` | An index of the two above |
| `GET /v1/agents/{agent_id}/a2a/well-known` | The same agent card, on an older path |

The card advertises `streaming`, `pushNotifications` and `extendedAgentCard` as
true, and adds an A2UI extension entry when the agent has `a2ui_enabled`. The
path layout anticipates proxying each agent to its own subdomain later.

One builder produces the card for every surface: the well-known routes and
`GetExtendedAgentCard` advertise the same interface URL, version and security
scheme. The extended card differs only in listing more skills.

### Authentication

A2A carries no authentication or permission model of its own. The subject is
resolved by the same dependency every optional-auth REST endpoint uses, handling
Kratos JWT, `aat_` API keys and Hydra OAuth alike, and the allow/deny decision
is made by the single edge authorizer. An API key that works over REST works
here unchanged, and the `/rpc` route requires the `agent:execute` permission.

### Delegating over A2A

When the binding is `a2a`, `A2AAgentTool` uses the official SDK client: it
sends `SendMessage` with `returnImmediately: true`, then polls `GetTask` on the
same endpoint every 2 seconds until terminal or until its budget runs out — 110
seconds, kept under the 120-second HTTP timeout. Each request stays short;
waiting is a series of polls rather than one long-held connection. The
configured `a2a_url` is the RPC endpoint itself; the tool does not fetch the
remote card.

It reads artifacts first, then falls back to `status.message`, and returns
`"(No output from agent)"` when neither carries anything. A JSON-RPC error from
the remote agent comes back as `success: false`; an HTTP failure raises.

A `402 Payment Required` response is handed to an optional payment handler
below the SDK client, at the HTTP transport, and the paid response is returned
to the client in its place.

## Why not make A2A the default for every agent-to-agent call

Because for a same-platform call it costs more and buys nothing. The local
binding already has a database session, a resolved workspace and a
`UserContext`; routing that through HTTP means serializing to JSON-RPC, opening
a connection to our own API, re-authenticating a subject we already
authenticated, and re-resolving a workspace we never left. None of those steps
changes the outcome.

There is also a behavioural difference that argues against it. The A2A
delegation budget is 110 seconds, bounded by the HTTP activity timeout; the
local binding's is 600 seconds. A same-platform delegation forced through A2A
abandons sub-agents that are still working, five times sooner, for no benefit.

What A2A earns is the trust boundary. When the target is someone else's agent,
there is no shared session to reuse, the wire format has to be a published
standard rather than an internal contract, and authentication has to be
explicit. That is exactly where the `a2a_url` setting points, and exactly where
the protocol's cost is worth paying.

The cost of keeping two bindings is that they are not equivalent, and the
differences are not always obvious from the outside — different timeouts,
different failure text, and a result-extraction path that goes through the A2A
mapping in one case and the task row in the other.

## Limits

- **`a2a-info.json` advertises endpoints that do not exist.** Its `endpoints`
  block names `rpc` at `/v1/agents/{id}/rpc` and `stream` at
  `/v1/agents/{id}/stream`. The real RPC route is `/v1/agents/{id}/a2a/rpc`, and
  there is no `/stream` route.
- **The card's skills are generic, not the agent's.** `text-processing` is
  always listed; `tool-execution` and `task-planning` appear based on whether
  the agent has tools or planning enabled. Attached
  [skills](/concepts/agents/skills) are never enumerated, so a remote caller
  cannot discover what an agent actually knows how to do.
- **Discovery endpoints bypass workspace scoping.** They read the agent row
  directly by id with no authentication and no `UserContext`, so any agent's
  name, description and status are readable by anyone who can guess or obtain
  its UUID.
- **`ListTasks` filters are not supported.** `contextId`, `status` and
  `statusTimestampAfter` are refused with `UnsupportedOperationError`; paging
  (`pageSize`, `pageToken`) works.
- **Push authentication schemes are not supported.** A push config must carry a
  `token`; one with `authentication` is refused.
- **Delegation over A2A can return a non-terminal result.** If the poll budget
  elapses, the tool returns the latest task it saw and logs a warning rather
  than failing. The caller receives whatever text was available at that moment.
- **Only JSON-RPC is implemented.** The gRPC and HTTP+JSON transports the spec
  permits are not built; v1.0.0 requires only one.
- **Push authentication is a single echoed bearer token.** There is no webhook
  ownership challenge and no JWT signing of notifications. There is also no
  cross-task cleanup of stale webhook configs.
- **A2A delegation polls rather than subscribes.** `SubscribeToTask` and
  `SendStreamingMessage` exist, but `A2AAgentTool` does not use them.

## Related

<Columns cols={2}>
  <Card title="Tasks" icon="diagram-project" href="/concepts/execution/tasks">
    The unit an A2A message becomes, and the states it reports back
  </Card>
  <Card title="Events" icon="diagram-project" href="/concepts/execution/events">
    The stream A2A streaming maps from
  </Card>
  <Card title="What is an agent" icon="robot" href="/concepts/agents/what-is-an-agent">
    Where the `a2a_url` setting lives on a tool config
  </Card>
  <Card title="Tool authorization" icon="scale-balanced" href="/concepts/governance/tool-authorization">
    The gate a `delegate_to_<agent>` call clears
  </Card>
</Columns>
