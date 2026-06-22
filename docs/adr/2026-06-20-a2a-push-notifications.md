# ADR: A2A Push Notifications over the Channel Delivery Pipeline

**Date:** 2026-06-20
**Status:** Accepted — implemented 2026-06-20
**Deciders:** Engineering team
**Related:** `docs/adr/2026-06-20-a2a-transport-correctness.md`,
`docs/adr/2026-05-21-event-architecture.md`

---

## Context

A2A v1.0.0 defines push notifications: a client registers a `PushNotificationConfig`
(webhook `url` + optional `token` + auth) for a task via
`CreateTaskPushNotificationConfig`. The server then POSTs notifications to that webhook as
the task progresses (notably on terminal state), so clients with no persistent connection
(serverless, mobile, disconnected) still receive results. The pre-cutover implementation
advertised `capabilities.pushNotifications=false` and returned `-32003` for the push-config
methods.

We already operate an **outbound channel delivery pipeline** (Telegram/Slack/Discord). It
is structurally the same problem: *on a task event, perform an HTTP delivery to an address
bound to the task.* That pipeline is durable and battle-tested:

| Stage | Code |
|---|---|
| Resolve delivery target from task | `agent_execution_activities.py::publish_workflow_events_activity._resolve_channel_origin` (~1326, 1432-1453) |
| Routing decision (visibility, dedup, format) | `channels/activity_emit.py::emit_channel_delivery` |
| Adapter registry | `channels/adapters.py::register_adapter`, `make_http_sender` |
| Durable drain + send | `channels/delivery_consumer.py::ChannelDeliveryConsumer` → `adapter.send` |
| Visibility / presentation | `workflows/visibility.py` (RESULT set) |

A reusable SSRF guard already exists: `agentarea_common/utils/url_safety.py`.

## Decision

**Model an A2A push webhook as another outbound channel type, `a2a_webhook`, and deliver
notifications through the existing channel pipeline. Do not build a parallel delivery
mechanism.**

### Persistence — split like channels: non-secret in `task_parameters`, secrets in the secret store

This mirrors exactly how channels are stored:
- **Channel non-secret config** → Postgres (`triggers` table) / per-task reply address in
  `task.task_parameters["channel_origin"]`.
- **Channel credentials** (bot_token, …) → secret store, key `channel_cred:<type>:<trigger_id>`,
  never returned in API responses (`channels/adapters.py:252`).

So for push:
- **Non-secret** (`id`, `url`, `presentation`, secret-ref) → `task.task_parameters["a2a_push_configs"]`
  as a list. Consistent with `channel_origin`; the delivery activity already reads
  `task.parameters`.
- **Secret** (`token` / `authentication`) → **secret store**, by analogy with `channel_cred`.
  A2A push has no standing trigger, so key by task + config: `a2a_push_token:<task_id>:<config_id>`.
  Read only at send time to sign the callback; **never** echoed by `get`/`list`.

Rationale: A2A push-config methods are always task-scoped (`list`/`get`/`delete` take a task
id), so no cross-task query justifies a table; the event-architecture ADR already rejected
new single-consumer tables as YAGNI; and keeping the token out of `task_parameters` JSON
avoids leaking it via `get`/`list` responses and logs — matching the channels precedent.
Revisit a table only if cross-task GC of stale webhooks is needed.

Also accept push config at **send time** via `MessageSendParams.configuration.pushNotificationConfig`
(currently missing from our `MessageSendParams`): it lands in `task_parameters` at submit,
exactly like `channel_origin`, so the standalone `set` method is optional sugar over the same
storage.

### Delivery — generalize one target to many

`publish_workflow_events_activity` resolves a single `channel_origin` today. Generalize to a
**list of delivery targets** = the inbound `channel_origin` (if any) + one synthetic
`{type: "a2a_webhook", url, token, config_id, presentation: "a2a_push"}` per registered push
config. Emit one `emit_channel_delivery` per target. Dedup key already includes the event id
and channel; extend with the target/config id so multiple webhooks each get their copy.

### Adapter — `a2a_webhook`

Register via `register_adapter("a2a_webhook", …)`:
- **formatter** builds the A2A notification body (full event, per decision below).
- **sender** = `make_http_sender` POSTing to `config.url`, echoing the client `token` in an
  `X-A2A-Notification-Token` header so the client can authenticate the callback.
- **SSRF guard**: validate `url` with `url_safety` both at `set` time (reject immediately)
  and before each send (config may have been crafted to bypass).

### Notification body — full event payload

The POST body carries the v1.0.0 streaming payload — a `StreamResponse` `statusUpdate`
wrapper (terminal `TaskState`, final answer in `status.message`, role `AGENT`, no `kind`/
`final`) — reusing the mapping helpers from `agents_a2a.py` (`map_workflow_event_to_sse` /
`convert_agent_task_to_a2a_task`).
Clients receive the result without a follow-up `GetTask`. (Minimal "ping then poll" was
considered and rejected: it adds a round-trip for no durability benefit since our delivery is
already durable.)

### Visibility

Add an `a2a_push` presentation mapping to `workflows/visibility.py` = RESULT (terminal
`WorkflowCompleted`/`Failed`/`Cancelled`) plus terminal STATUS. Push is not a chat firehose;
intermediate chunks are not pushed.

### RPC methods + capability

- Flip `capabilities.pushNotifications=true`.
- Implement `Create|Get|List|DeleteTaskPushNotificationConfig` against the JSON list, with
  the v1.0.0 **flat** `TaskPushNotificationConfig` shape (`{taskId, id, url}` — no nested
  `pushNotificationConfig`) — replacing the placeholder `-32003` branch. `delete` returns `null`.
- Keep `-32003 PushNotificationNotSupportedError` only as the pre-flip fallback.

### Multiple configs

Supported (A2A allows N configs per task, each with an `id`). The JSON list holds them;
`set` upserts by id (generating one if absent), `list` returns all, `delete` removes by
`pushNotificationConfigId`.

## Non-goals (deferred)

- Webhook ownership verification (A2A's optional challenge handshake).
- JWT-signed notifications / advanced auth schemes (only the echoed bearer token for now).
- Cross-task config management / TTL GC (would motivate a table — out of scope until needed).

## Consequences

- A2A push reuses the durable outbound pipeline (Redis stream + consumer + Temporal activity
  retry) — no new delivery/retry code, no drift from channel delivery.
- One new adapter + a list-of-targets generalization + 4 thin RPC handlers + SSRF wiring.
- `task_parameters` carries a small list per task; acceptable at expected scale.
- SSRF is the principal risk and is mitigated by the shared `url_safety` guard at set + send.
