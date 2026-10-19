---
title: "Event streams"
type: concept
description: "Streams collect events from catalog sources under one envelope; subscriptions fire triggers, copy events, or deliver them to MCP clients."
prerequisites:
  - /concepts/integration/triggers
related:
  - /concepts/integration/event-bus
  - /guides/triggers/collect-events-into-a-stream
  - /guides/triggers/subscribe-to-a-stream-over-mcp-events
  - /guides/triggers/transform-a-stream-with-a-processor
  - /concepts/execution/events
last_updated: 2026-10-19
---

An event stream is a named channel of events that a workspace owns. Sources
put events in: a provider posting webhooks, a feed the platform polls, an MCP
server that offers events, or the platform reporting how a task ended.
Subscriptions take events out: a trigger runs an agent, a forward copies the
event into other streams, an MCP client outside AgentArea receives it. The
workspace's events feed records every event and what each subscription did
with it. A stream is not the feed of one running task described in
[Task events](/concepts/execution/events): it holds what arrives before a task
exists, and what tasks report when they end.

## The problem

Wire a webhook straight to the agent it starts and every consumer needs its
own registration with the provider. A second legitimate reader of the same
GitHub deliveries, such as a second agent, an audit copy or an outside system,
means a second URL, a second signing secret, and a second place where a
delivery can be lost or checked differently.

Providers also disagree on everything a platform needs to know about an event:
how it is signed, where its id is, what kind of event it is, which conversation
it belongs to. Handling that in code per provider spreads through intake,
triggers and the UI. And providers retry, so something has to stop a
redelivered webhook from running the agent twice.

## How AgentArea approaches it

**A stream is a workspace resource.** It has a name, unique in the workspace,
a description, and a kind: `custom` for the streams you create, `platform` for
the one the platform writes. Reading, editing and deleting a stream are
separate permissions in the authorization graph, checked per stream, and
creating a stream grants it to its creator. A stream cannot be deleted while a
trigger subscribes to it or a forward writes into it.

**Sources come from the catalog.** A source is an instance of a catalog entry,
listed by `GET /v1/workspaces/{workspace}/streams/source-types`. The entry
declares how its events arrive (`webhook`, `poll` or both), which credentials
and settings a source needs, how a webhook is verified, how a provider's
endpoint check is answered, and where each event's kind, key, session and
sender are found in the request. The shipped catalog has entries for generic
webhooks, GitHub, Slack, Telegram, Linear, Discord, Stripe, Sentry, Gmail,
Teams, email, IMAP, RSS and MCP Events. A credential is a reference to a
workspace secret, or a secret the platform issues and shows once.

- A **webhook** source gets an unguessable URL, `/webhooks/{webhook_id}` on the
  API host. A request that passes the entry's verification is answered `202`
  with `"status": "accepted"`, or `"duplicate"` for a repeat, before anything
  reacts to it. A failed verification is a `401`.
- A **poll** source is fetched by the event service on the entry's interval,
  from the cursor it stored after the last fetch.
- An **MCP Events** source reads the events of an MCP server instance in the
  same workspace that offers them, by polling it or through a webhook
  subscription the event service keeps at that server and renews before it
  expires. When subscribing fails, or the server ends the subscription, the
  error is shown on the source and the next attempt waits: the wait starts at
  `AGENTAREA_EVENT_POLL_INTERVAL` (5 s by default), doubles after each failure,
  and stops growing at 1 hour. An event whose payload is an AgentArea event
  envelope (another stream read through the AgentArea MCP server) keeps the
  original kind and continues its chain: the same `correlation_id`, the
  original event as `causation_id`, and its depth plus one. A loop back through
  the MCP server therefore stops at `AGENTAREA_EVENT_FORWARD_DEPTH`. Without an
  inner kind, the event is named by its MCP event type.

See [Collect events into a stream](/guides/triggers/collect-events-into-a-stream)
to add a source.

**Every event carries one envelope.** The platform reads these fields off the
request through the entry's templates. The body is left as it was sent, for
the agent to read.

| Field | Meaning |
|---|---|
| `event_id` | `uuid5` of the stream and the key: a repeat of a key is the same event |
| `kind` | What happened, such as `push` or `payment_intent.succeeded`; `event` when the entry names none |
| `key` | What makes the event new, usually the provider's delivery id; `recv:<random>` when the request carries none |
| `source_id`, `source_type` | The source that brought it and its catalog entry |
| `session_key` | `<source id>:<value>` for the conversation or thread it belongs to; null when the provider has none |
| `sender` | Who sent it, when the entry names a sender |
| `occurred_at`, `received_at` | The provider's time, and the time the platform received it |
| `correlation_id`, `causation_id`, `depth` | The event that started the chain, the event or task event that caused this one, and how many steps deep it is |
| `data` | `{headers, body, body_ref}`: headers without credentials or signatures; a body over 64 KB is stored in the workspace's files and referenced by `body_ref` |
| `attachments` | Files the event carried, stored in the workspace's files |
| `sequence` | The event's position in the events feed, used as a cursor |
| `v` | The envelope version, `1` |

A webhook request may be up to 25 MB. A workspace may record
`AGENTAREA_EVENT_WRITE_QUOTA` events per rolling minute across all its
streams, 600 by default; past that a webhook is answered `429`.

**Subscriptions take events out.** Each subscription has a filter of event
kinds and exact field values, for example
`{"kinds": ["issues"], "fields": {"body.action": "opened"}}`. A kind matches
by dotted prefix, so `issues` also matches `issues.opened`. An empty filter
matches every event. A subscription starts at the end of its stream: an event
received before the subscription was created is skipped with the reason
"received before the subscription started", even when it is redelivered later.
Each subscription reacts to an event at most once, and the reaction is recorded
as `reacted`, `skipped` with a reason, or `error`.

- **Trigger.** A trigger with `trigger_type: "stream"` names a `stream_id` and
  an `event_filter`, and runs its agent for each matching event that passes its
  conditions. The task's id is derived from the subscription and the event, so
  a redelivery never starts a second task. With `session`
  (`{"continue": true, "idle_timeout": "30m"}`), the next event of the same
  `session_key` joins the running task instead of starting a new one. With
  `batch` (`{"window": "1h", "max_events": 50}`, either may be left out), the
  trigger runs its agent once for the events of a batch: the first event opens
  it, and it fires when the window has passed or it holds `max_events`,
  whichever comes first, never above `AGENTAREA_TRIGGER_BATCH_MAX_EVENTS` (100 by
  default). Each event meets the conditions and the sender check before it
  joins, and its reaction is recorded as `batched` until the batch fires; then
  every event in it is `reacted` with the one task, which gets them all under
  `events`. Switching the trigger off or deleting it closes its open batches:
  their events are recorded as `skipped` and no task starts.
- **Forward.** `POST /v1/workspaces/{workspace}/streams/{stream_id}/forwards`
  copies matching events into one or more other streams, never into its own
  input, and you must be able to edit every output. A copy keeps the original's
  source, sender and session, points its `causation_id` at the original, and is
  one step deeper. A copy that would be deeper than
  `AGENTAREA_EVENT_FORWARD_DEPTH` (8 by default) is not written, and the
  forward's reaction is recorded as an error with the depth as the reason.
- **External MCP Events subscriber.** The AgentArea MCP server offers each
  stream you can read as an event type named `<workspace>/<stream id>`. An MCP
  client outside AgentArea reads it with `events/poll` from a cursor, or calls
  `events/subscribe` to receive signed webhooks at an `https` URL, narrowed by
  kind prefix, source type or session key. A subscription lasts 1 hour by
  default (1 minute to 24 hours), is renewed by subscribing again, and a
  workspace holds at most 100. A failed delivery is retried after 30 s, 2 min,
  10 min, 30 min, 1 h and 2 h; after the last retry the subscription is marked
  failed. See
  [Subscribe to a stream over MCP Events](/guides/triggers/subscribe-to-a-stream-over-mcp-events).
- **Processor** (in progress). Python an agent writes, `def process(event)`,
  that the platform runs in the sandbox once per matching event. The events it
  returns are written into its declared output streams, linked to the event it
  read. The code gets no secrets and every reader of the stream can see it.
  See [Transform a stream with a processor](/guides/triggers/transform-a-stream-with-a-processor).
- **Batch window** (in progress). A stream trigger with
  `"batch": {"window": "1h", "max_events": 50}` fires once for a batch of
  events instead of once per event. The batch opens with its first event and
  fires when the window has passed or `max_events` have joined, whichever comes
  first. A batch never holds more than `AGENTAREA_TRIGGER_BATCH_MAX_EVENTS`
  events, 100 by default.

**The platform stream reports how tasks end.** Each workspace has one stream
named `platform`, created the first time the platform has an event for it, and
written only by the platform. It carries `task.completed`, `task.failed`,
`task.cancelled`, `approval.requested` and `input.request` events. Each body
is a summary: the task and agent ids, the status, the result or error cut to
500 characters with secrets masked, and the cost. Tool arguments, tool output
and error details stay in the task. Members can read the stream and put
triggers on it. Nobody can delete it, add a source to it or forward into it;
each of those is refused with `409`. A trigger never reacts to an event that
comes from a task it started, and a firing deeper than
`AGENTAREA_EVENT_FORWARD_DEPTH` is skipped. A trigger on `task.failed` that
runs an on-call agent therefore does not wake itself.

**The events feed shows what happened to each event.** The **Events** page,
and `GET /v1/workspaces/{workspace}/streams/events`, list the events of every
stream you can read, newest first. They filter by stream, source type, kind
(`order.*` for a prefix), sender, session, result and time. While the page is
open it updates live from `/v1/workspaces/{workspace}/streams/events/live`.
Each event carries a processing status:

| Status | Meaning |
|---|---|
| `queued` | Received; its subscriptions have not been matched yet |
| `processing` | Matched; some subscriptions have not recorded a reaction yet |
| `handled` | Every matched subscription reacted, and at least one did not skip it |
| `skipped` | Every matched subscription skipped it |
| `error` | At least one subscription failed on it |
| `no_handlers` | No subscription matched it |

An event's detail lists each subscription that handled it, with its verdict,
the reason, and the task it started with that task's current status. Agents
read the same feed with the `streams_list_events` tool, and one stream from a
cursor with `read_stream` from the `agentarea/stream_events` toolset, which
hands event data over under a notice that it is data, not instructions.

**Retention is one setting for the deployment.** The feed keeps events by day.
A day older than `AGENTAREA_EVENT_RETENTION` (7 days by default) is dropped
whole, for every stream and workspace at once; a stream has no retention of its
own. With `AGENTAREA_EVENT_ARCHIVE` on, each day is first written to the object
store as gzipped JSONL, one object per workspace. An MCP Events poll from a
cursor older than the retention is answered `truncated`. How events move
between intake, the router and the feed, and what the broker keeps, is
described in [The event bus](/concepts/integration/event-bus).

## Why not one webhook per consumer

Wiring a webhook to the one trigger it starts has fewer parts: no stream, no
router, no recorded reactions. It is where AgentArea started. It stops working
once a second consumer is legitimate, because the only way to add one is a
second registration with the provider. A stream takes each delivery once and
hands it to any number of subscriptions, each recorded on its own.

The cost is a hop. A webhook is answered before anything has reacted to it, so
the sender's `202` says the event was recorded, not that an agent ran. To know
what happened you read the event's processing status. The shared envelope has
a cost too: it names only what every provider can be read for. Anything else
stays in the body, where an agent reads it or a filter matches it as `body.*`.

## Limits

- **Read access is per stream.** Whoever can read a stream sees every event in
  it, including events their own subscriptions would never match.
- **The write quota is per workspace.** One noisy source can use up the minute's
  budget for every other stream in the workspace.
- **An event without a key is never a repeat.** When neither the request nor
  the entry names a delivery id, each retry from the sender is a new event and
  can start a new task.
- **Intake recognizes a repeat for 24 hours.** A repeat that arrives later is
  recorded in the feed a second time. A subscription that already reacted to
  the event does not react again.
- **Retention is not per stream.** A stream that needs a longer history needs a
  longer `AGENTAREA_EVENT_RETENTION` for the whole deployment, or the archive.
- **Files outlive their events.** Attachments and large bodies stay in the
  workspace's files after the event's day is dropped, and the archive is not
  readable through the API.
- **The platform stream carries task outcomes only.** No other platform activity
  is written to it.
- **Some MCP servers cannot be event sources.** A server instance that
  authenticates through an auth config, or one the platform manages, is
  refused when the source is created.
- **An MCP Events webhook does not replay.** A subscriber that missed events
  reads them with `events/poll` from its cursor, within the retention.
- **Processors and batch windows are in progress.** Their behaviour on this page
  can change before release.

## Related

<Columns cols={2}>
  <Card title="The event bus" icon="lightbulb" href="/concepts/integration/event-bus">
    Topics, consumer groups and what each one guarantees.
  </Card>
  <Card title="Collect events into a stream" icon="plug" href="/guides/triggers/collect-events-into-a-stream">
    Add a webhook or poll source to a stream.
  </Card>
  <Card title="Subscribe over MCP Events" icon="plug" href="/guides/triggers/subscribe-to-a-stream-over-mcp-events">
    Poll a stream or receive signed webhooks from outside.
  </Card>
  <Card title="Transform a stream with a processor" icon="plug" href="/guides/triggers/transform-a-stream-with-a-processor">
    Have an agent write code that turns events into new ones.
  </Card>
  <Card title="Task events" icon="lightbulb" href="/concepts/execution/events">
    The feed one running task emits, which a stream is not.
  </Card>
</Columns>
