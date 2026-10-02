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
last_updated: 2026-10-01
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

`AgentToolFactory.create_tool` picks a binding for the target and wraps it in a
`DelegationTool` facade. The facade forwards `name`,
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

With an `a2a_url`, nothing is looked up on this platform: the tool config's
`name` is only the label the model sees, and the description comes from
`settings.description_override`. Without one, the target is resolved by name in
the caller's workspace.

Delegates are checked when the agent is saved, not when it is read, so a stored
config that no longer passes still loads. Saving is refused with `400
invalid_delegate` when a local delegate names no agent in the workspace, an
`a2a_url` is not an http(s) URL with a host, or two delegates' names sanitize
to the same tool name.

The tool name is derived from that name, sanitized to `delegate_to_<name>`, and
both bindings produce the same one-parameter schema: a `message` string.

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

### Addresses

Every agent has an address of its own: a host, built from `A2A_AGENT_URL` with
the agent id as the first label, such as
`https://4f1c….a2a.agentarea.ru`. The agent API returns it as `a2a_url`. On
that host the agent card is at the well-known path, and the JSON-RPC endpoint
is the root:

```http
GET  https://{agent_id}.a2a.example.com/.well-known/agent-card.json
POST https://{agent_id}.a2a.example.com/
```

Anything else on that host is `404`: the host serves the agent and nothing of
the rest of the API.

One host per agent is what the spec implies rather than a choice of style. The
spec places the card at `/.well-known/agent-card.json` on the agent's origin
(RFC 8615) and leaves the endpoint to the card, so an origin can describe one
agent. A client is handed only the address, reads the card, and takes the
endpoint, transport and auth scheme from there.

The same agent also answers under the API host, for clients configured before
agents had their own host:

```http
GET  /v1/agents/{agent_id}/.well-known/agent-card.json
POST /v1/agents/{agent_id}/a2a/rpc
```

Each card names the endpoint on the host it is served from, built from
configuration rather than from the request: `A2A_AGENT_URL` for the agent's
own host, `API_BASE_URL` for the API host. A client is never sent to a host
other than the one it was given.

### The endpoint

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

Five unauthenticated endpoints describe an agent:

| Endpoint | Returns |
|---|---|
| `GET https://{agent_id}.<zone>/.well-known/agent-card.json` | The A2A agent card, on the agent's own host |
| `GET /v1/agents/{agent_id}/.well-known/agent-card.json` | The A2A agent card |
| `GET /v1/agents/{agent_id}/.well-known/a2a-info.json` | Protocol and endpoint metadata |
| `GET /v1/agents/{agent_id}/.well-known/` | An index of the two above |
| `GET /v1/agents/{agent_id}/a2a/well-known` | The same agent card, on an older path |

The card advertises `streaming`, `pushNotifications` and `extendedAgentCard` as
true, and adds an A2UI extension entry when the agent has `a2ui_enabled`.
`a2a-info.json` and the index report the agent's address as `a2a_url`.

One builder produces the card for every surface: the well-known routes and
`GetExtendedAgentCard` advertise the same version and security scheme, and the
interface URL of the host they are served on. The extended card differs
only in listing more skills.

### Authentication

A2A carries no authentication or permission model of its own. The subject is
resolved by the same dependency every optional-auth REST endpoint uses, handling
Kratos JWT, `aat_` API keys and Hydra OAuth alike, and the allow/deny decision
is made by the single edge authorizer. An API key that works over REST works
here unchanged, and the JSON-RPC route requires the `agent:execute` permission.

A member of the agent's workspace may call it. A caller outside the workspace
uses a key bound to the agent: an API key created with `agent_id`, from the
agent's **Settings → A2A access**. Such a key acts as the member who issued it,
for that one agent only. The edge authorizer admits it on that agent and
refuses it on every other one, and every authenticated REST route and the MCP
surface refuse it with `403`, so handing it out opens no workspace data.

Inside A2A the key is a guest, not a member. It sees only the tasks it started:
`GetTask`, `CancelTask`, `SubscribeToTask` and the push-config methods answer
`TaskNotFoundError` for any other task of the agent, and `ListTasks` is refused
with `UnsupportedOperationError`. It never acts as a workspace admin, even when
its issuer owns the workspace. The run it starts executes as its issuer, the
way a trigger's run executes as the trigger's creator. The key stops working
when it is revoked or when its issuer leaves the workspace.

### Delegating over A2A

When the binding is `a2a`, `A2AAgentTool` uses the official SDK client: it
sends `SendMessage` with `returnImmediately: true`, then polls `GetTask` on the
same endpoint every 2 seconds until terminal or until its budget runs out — 110
seconds, kept under the 120-second HTTP timeout. Each request stays short;
waiting is a series of polls rather than one long-held connection.

The configured `a2a_url` is the agent's address. Each call reads the card at
`/.well-known/agent-card.json` there and sends the message to the endpoint the
card names. A card that names an endpoint on another origin is refused before
anything is sent, because the credential was bound to the address an admin
approved, not to wherever a card points. Saving stores the address however it
was pasted: a card URL or a trailing slash is reduced to the origin or base
path the card is found under. The agent form reads the card while a remote
delegate is being added, through `POST /v1/workspaces/{workspace}/a2a/agent-cards`,
so a wrong address is caught before it is saved.

The credential is a reference, not a value. `settings.auth_secret_name` names a
secret in the calling agent's workspace; the worker reads it when the delegate
is called, not when the agent is saved or the tool is built, and sends it as
`Authorization: Bearer`. A secret that no longer exists fails that call with an
error naming the secret.

Binding a secret to a URL sends that secret to whoever serves the URL, so it
takes the same authority as reusing a secret for a provider key: only a
workspace admin may add a binding or change the URL or secret of one. A member
may still edit the rest of an agent that already carries a binding. The secret
must exist in the workspace and must not be managed by a connection, whose
rotations would silently change it. Setting `auth_secret_name` without
`a2a_url` is refused.

The URL is member-supplied, so every request goes through the same outbound
guard as OpenAPI connections: an `a2a_url` that resolves to a private address is
refused unless the deployment allows it through `OUTBOUND_PRIVATE_ALLOWLIST` or
`ALLOW_PRIVATE_URLS`.

Only `TASK_STATE_COMPLETED` is a success. The tool reads artifacts first, then
falls back to `status.message`, and returns `"(No output from agent)"` when
neither carries anything. Any other terminal state, a task stopped at
`TASK_STATE_INPUT_REQUIRED` or `TASK_STATE_AUTH_REQUIRED` (polling ends there,
since the remote agent is waiting on its caller), and a task still running when
the budget runs out all come back as `success: false` with the remote `task_id`
and `task_state`, so the calling model is told the delegate did not answer
rather than handed an empty answer. A JSON-RPC error from the remote
agent is also `success: false`; an HTTP failure raises.

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
- **A2A delegation gives up after 110 seconds.** A remote task still running
  then is reported as a failure carrying its `task_id`; the remote task keeps
  running, and its result never reaches the caller.
- **A delegated A2A task is not linked to the task that delegated it.** On the
  receiving side it is an ordinary task started by whoever issued the key, so
  the caller's task view does not show it as a child.
- **An agent in another workspace of the same deployment is reached over A2A.**
  The local binding resolves names only in the caller's workspace, so crossing
  workspaces pays the A2A cost and limits above — see
  [delegate to an agent in another workspace](/guides/agents/delegate-to-another-workspace).
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
  <Card title="Delegate to another workspace" icon="robot" href="/guides/agents/delegate-to-another-workspace">
    Hand tasks to your agent in a different workspace
  </Card>
</Columns>
