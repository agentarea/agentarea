---
title: "Event streams"
type: concept
description: "The append-only journal a workspace owns, and how subscriptions turn its events into trigger runs or copies in other streams."
prerequisites:
  - /concepts/integration/triggers
related:
  - /guides/triggers/collect-events-into-a-stream
  - /guides/triggers/trigger-from-a-webhook
  - /concepts/execution/tasks
  - /concepts/execution/events
last_updated: 2026-10-07
---

An event stream is a named, ordered log that a workspace owns. A webhook
delivery, or anything else recorded into it, becomes a row nobody can rewrite,
and any number of subscriptions can read the same log independently, each at
its own position. This is not the task execution feed described in
[Events](/concepts/execution/events) — that is what one task emits while it
runs. A stream is what arrives *before* any task exists, and the durable
record of which subscriptions acted on it and what they decided.

## The problem

Before a stream existed between them, a webhook and its trigger were wired
directly: registering the webhook and firing exactly one trigger were the same
step, and a trigger's own execution history was the only record of what had
come in. That works fine while a webhook has exactly one consumer. It breaks
the moment a second one is legitimate — an agent and an audit copy of the same
GitHub deliveries, or two agents each filtering a different event kind out of
one repository — because direct wiring has no way to say "deliver this once,
to more than one place." Adding a second consumer meant registering the
webhook a second time with the provider: a second URL, a second signing
secret, a second chance to miss a delivery or verify it differently.

A provider's own retries raise a second question: what stops a redelivered
webhook from running the agent twice? And a third: what stops one sender from
writing enough events to exhaust a workspace's storage, or drowning out every
other source sharing the account?

## How AgentArea approaches it

**A stream is a workspace-scoped, graph-governed resource.** `StreamORM`
(`__graph_resource__ = True`) carries a `name` unique per workspace, a `kind`,
and `retention_days`. Every stage-1 stream — created directly through
`POST /v1/workspaces/{workspace}/streams/` or auto-created for a webhook
trigger — is `kind: "custom"`; `platform` and `processor_output` exist in the
enum for later use but nothing produces them yet. Creating a stream grants its
creator; reading, editing, and deleting are separate graph permissions
(`requires("read"/"edit"/"delete", "stream", ...)`) checked per stream, not
per event.

**A source is where events enter.** The only kind in stage 1 is `webhook`: a
`stream_sources` row carrying `webhook_id`, `webhook_type`, `allowed_methods`,
`validation_rules`, and `webhook_config` — exactly the fields a webhook
trigger used to keep on itself. Creating a `webhook` trigger auto-creates a
stream, a source on it, and a subscription that fires the trigger; the trigger
API stays the surface you edit, and `TriggerService` mirrors every change onto
the source in the same request, so nothing about using a webhook trigger
changed except where the row that remembers its configuration lives.

**A source can also stand alone, with no trigger.**
`POST /v1/workspaces/{workspace}/streams/{stream_id}/sources` adds a webhook
source to any stream you may edit, of a type listed by
`GET /v1/workspaces/{workspace}/streams/source-types` — `generic`, `github`,
`sentry`, `yookassa`, `stripe`, `telegram`, `slack`, `email`. Each type
declares the credentials its verifier needs, and creation without a required
one is refused rather than accepted unsigned; `generic` and `email` take an
optional signing secret and are issued one, shown once, when it is left out.
A credential is held by reference: the source's entry in the secret store
names the workspace secret you picked, the value is read from that secret at
each delivery, and a `secret_references` row keeps the secret from being
deleted while a source uses it. Sentry is verified by the HMAC-SHA256 of the
body in `Sentry-Hook-Signature`. YooKassa signs nothing, so its notification
is checked against its API instead: the notified object is read back with the
shop's id and key, and the event is recorded only when YooKassa answers that
object in the notified state; an unreachable API is a refusal, not a pass. A
source a webhook trigger owns cannot be deleted on its own, and neither can a
stream such a source still feeds — the trigger goes first. See [Collect events
into a stream](/guides/triggers/collect-events-into-a-stream).

**Appending is idempotent, size-capped, and quota-limited.**
`StreamJournal.append` requires an `event_key` naming what makes this event
new. For a webhook, that is the provider's own delivery id when it sends
one — a header (GitHub's `X-GitHub-Delivery`, Linear's `linear-delivery`, or
a generic `webhook-id` or `Idempotency-Key`) or, failing that, a body field
(Stripe's `id`, Telegram's `update_id`, Slack's `event_id`); Sentry's
`Request-ID` header names its deliveries, and a YooKassa notification is keyed
by its `event` and object `id` together — and a fresh
`recv:<uuid4()>` otherwise, which is explicitly never recognized as a repeat. The key is enforced with `INSERT ... ON CONFLICT DO
NOTHING` on `(stream_id, event_key)`, so a redelivered id lands once: the
first attempt gets `sequence` and `appended: true`, every later one gets the
same `sequence` and `appended: false`. The event's own id is deterministic too
— `uuid5` of the stream id and the key — so retrying the same key always reads
back the same event. A payload over 256 KiB is refused outright, and a
workspace appending more than `AGENTAREA_EVENT_WRITE_QUOTA` events across
*every* stream it owns in the trailing minute is refused with a quota error —
the webhook endpoint turns both into `413` and `429`. Appends to one stream are
ordered by locking that stream's row for the duration of the insert, against
one global sequence shared by every stream in the deployment.

**Intake answers before anything reacts.** A webhook request that passes
method, signature, and the checks above is recorded and answered `202` with
`{"status": "accepted", "sequence": n}` (`"duplicate"` instead of
`"accepted"` on a repeat) — never run inline with the HTTP request. What
happens next is a separate hop. See [Trigger an agent from a
webhook](/guides/triggers/trigger-from-a-webhook) for the full request
lifecycle, including the two provider handshakes that are answered
synchronously instead and never appended.

**A subscription reads the journal independently, at its own pace.** Two
kinds exist: `trigger`, which fires a trigger for events that match, and
`forward`, which copies matching events into one or more other streams. Each
subscription's `filter` names the event kinds it wants (dotted-prefix
matching, so `issues` also catches `issues.opened`) and exact field values;
an empty filter matches everything. Each subscription keeps its own
`cursor_sequence`, so adding a second subscription to a stream that already
has years of events starts it at today, not at the beginning — and one
subscription falling behind or failing never blocks another reading the same
log.

**The dispatcher runs inside the worker, leased rather than locked.** It polls
every `AGENTAREA_EVENT_DISPATCH_EVERY` and wakes sooner on a Redis pub/sub
signal (`agentarea.streams.wake`) published after a commit — the wake is
latency only; a publish failure falls back to the next poll instead. Due
subscriptions are claimed with `FOR UPDATE SKIP LOCKED` and a lease
(`AGENTAREA_EVENT_LEASE`), not a held row lock, because firing a trigger
commits inside `TriggerService`'s own session partway through handling — a
lock held across that would be released early. Events are handled one at a
time, up to `AGENTAREA_EVENT_DISPATCH_BATCH` per pass; a failed event retries
with exponential backoff (capped at five minutes) for up to
`AGENTAREA_EVENT_MAX_ATTEMPTS` tries, after which the outcome is recorded
`error` and the cursor still advances past it — one event that can never
succeed does not block everything queued behind it forever.

**Every event a subscription's filter matched gets exactly one outcome.**
`subscription_outcomes` is unique per `(subscription_id, event_sequence)`:
`reacted` (with the `task_id` it created, or the stream ids it forwarded
into), `skipped` (a condition declined, or the trigger is paused), or `error`.
An event no filter matched gets **no** outcome row at all for that
subscription — "nobody listened" is a distinct, visible state, not a success
with no effect. A trigger's `task_id` is itself deterministic — `uuid5` of the
subscription id and the event's sequence — so a crash between creating the
task and advancing the cursor is recognized on retry instead of starting a
second run.

**A forward copies an event, not a model.** `ForwardHandler` appends the same
`data` into every output stream, tagging the copy's `correlation_id` back to
the original and `causation_id` to the specific event, one `depth` deeper.
Forwards refuse to target their own input stream, and a chain of forwards
through other streams is bounded by `AGENTAREA_EVENT_FORWARD_DEPTH` causation
hops rather than left to loop. Outputs are written in sorted stream-id order,
so two forwards sharing outputs cannot lock them in opposite orders and
deadlock. A forward that hits the write quota fails and retries exactly like a
webhook delivery would — it is never silently dropped.

**Any trigger can subscribe to any stream, not only its own.** `webhook`
triggers keep auto-creating their stream as before. Deleting one keeps the
stream and its history; re-creating it under the same name and `webhook_id`
(to keep the sender's URL) takes that stream over, starting after the events
already in it, provided nothing else feeds it and the creator may edit it.
Stream names are unique per workspace; a taken name is a `409`. A `stream` trigger has no
intake of its own: it names an existing `stream_id` and `event_filter`
directly and rides the same dispatcher path. Firing still checks that the
person who configured the trigger can still run its agent — a configurer who
lost access gets the trigger stopped and marked `needs_owner` instead of a
firing. Enabling it again clears the mark; the next event re-checks access and
stops it again if that person still cannot run the agent.

**An agent can read a stream instead of being fired by it.** The
`agentarea/stream_events` toolset has one tool, `read_stream(stream,
after_sequence, limit)`: events after a sequence, oldest first, with
`next_after` to pass next time and `has_more` when another page is waiting. It
resolves the stream by name or id inside the caller's workspace, checks `read`
on it, strips credential headers from each event's data, and hands the data
over under the same untrusted-data notice a trigger's event block carries. The
platform keeps no cursor for it: the reader passes its own `after_sequence`.

**Partitions are maintained ahead of need, not on demand.** `stream_events` is
partitioned by day on `received_at`. A worker job keeps
`AGENTAREA_EVENT_PARTITIONS_AHEAD` days created ahead of today, drops whole
partitions older than the longest `retention_days` configured on any stream in
the deployment (floored at `AGENTAREA_EVENT_RETENTION`), and separately trims
a shorter-lived stream's own rows out of partitions still being kept for
someone else's longer one. Each step commits on its own and deletes go in
bounded batches. Creating or dropping a partition locks the whole journal, so
it waits at most 5 seconds for that lock and otherwise leaves the partition to
the next hourly pass rather than queue webhook intake behind it.

## Why not keep a webhook wired to exactly one trigger

Wiring a webhook straight to the one trigger it starts is simpler: no
dispatcher, no lease, no extra hop between "received" and "acted on." It is
also where AgentArea started. It stops scaling the moment a second consumer
is legitimate, because direct wiring cannot express "more than one of
something should see this" — the only way to add a second consumer was a
second registration with the provider. A shared, ordered log that any number
of subscriptions can read independently, each from whatever point it joined,
removes that duplication entirely; the cost is exactly what this page
describes — a worker process in the loop, a lease to coordinate it, and a
request that is answered before anything has actually reacted to it.

## Limits

- **`platform` and `processor_output` streams are declared, not produced.**
  Every stream in this release is `kind: "custom"`. Nothing in stage 1
  publishes a platform-originated event into a stream.
- **`read_stream` keeps no cursor.** A scheduled agent that wants only what
  is new must store `next_after` somewhere it can read next run, or read a
  stream whose retention matches its period from the start.
- **A YooKassa notification is believed only while the object is still in the
  notified state.** A delivery that arrives after the object moved on (a
  `payment.waiting_for_capture` read back as `succeeded`) is refused, and if
  every retry of it comes that late, that earlier state is never recorded.
- **Authorization is per stream, not per event or per subscriber.** Anyone who
  can read a stream sees every event in it, including ones no subscription of
  theirs would ever have matched. There is no audience scoping within a
  stream in this release.
- **The write quota is workspace-wide.** `AGENTAREA_EVENT_WRITE_QUOTA` counts
  appends across every stream the workspace owns in the trailing minute; one
  noisy source can exhaust the budget for every other stream next to it.
- **Dedup holds only within retention.** `stream_event_keys` rows are pruned
  together with the events they protect. A delivery repeating a provider id
  that aged out of retention is recorded as new, not recognized as a repeat.
- **A webhook with no provider delivery id is never deduplicated**, by design
  — a `recv:<uuid4()>` key cannot tell a retry from a first attempt, so a
  sender that retries without a stable id gets a second row, a second
  dispatch, and, for a trigger subscription, a second task.
- **A poisoned event can still exhaust its retries.** Past
  `AGENTAREA_EVENT_MAX_ATTEMPTS`, the cursor advances anyway and the outcome
  is recorded `error`; nothing retries it again later, and nothing pages
  anyone — the outcome row, found by reading the stream, is the only trace.

## Related

<Columns cols={2}>
  <Card title="Trigger an agent from a webhook" icon="plug" href="/guides/triggers/trigger-from-a-webhook">
    Create the webhook whose deliveries become a stream's events.
  </Card>
  <Card title="Tasks" icon="diagram-project" href="/concepts/execution/tasks">
    What a `reacted` outcome's `task_id` points at.
  </Card>
  <Card title="Events" icon="diagram-project" href="/concepts/execution/events">
    The task execution feed this journal is not.
  </Card>
</Columns>
