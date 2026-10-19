---
title: "The event bus"
type: concept
description: "How events move between intake, streams, triggers, the platform stream, MCP Events and the events page: broker topics read by consumer groups."
prerequisites:
  - /concepts/integration/event-streams
related:
  - /concepts/integration/triggers
  - /guides/triggers/subscribe-to-a-stream-over-mcp-events
  - /guides/triggers/collect-events-into-a-stream
  - /concepts/execution/events
last_updated: 2026-10-19
---

Every event AgentArea receives or produces travels through a broker:
Redis Streams by default. Writers append to a topic. Consumer groups read the
topic, and each group does exactly one job: route an event to the triggers that
want it, write it to the events read model, or send it somewhere outside.
Postgres holds what is state or a record: the events read model, the reactions,
tasks and their log. Postgres holds no queue. This page describes those topics
and groups and what each one guarantees.

## The problem

An event has more than one reader, and they do not move at the same speed. A
GitHub delivery fires a trigger. The same delivery belongs on the events page,
may be forwarded to another stream, and may be sent to an MCP client that
subscribed from outside. If one loop did all of that in order, a slow webhook
receiver would hold back the trigger, and a crash halfway through would leave
the event half handled. You could not tell which half had run.

Each reader also needs the usual queue guarantees: a position it resumes from,
redelivery after a crash, a cap on retries, and a place for messages that never
succeed. Building those in Postgres means writing them yourself, with a
dispatcher, leases and polling. That is what the first version of event streams
did.

## How AgentArea approaches it

**Topics.** Every topic name is
`<AGENTAREA_EVENT_NAMESPACE>.<domain>.<dataset>`, for example
`agentarea.streams.events.3`. Two deployments can share one Redis by choosing
two namespaces.

| Topic | Written by | Read by |
|---|---|---|
| `streams.events.0` to `streams.events.N-1` | webhook intake, the `ingest` group, forwards, the `platform` group | groups `router` and `events-view` |
| `streams.ingest` | the Go event-service: items it polled | group `ingest` |
| `tasks.events` | the `record` activity of every task run | groups `delivery` and `platform`; each API process's live feed, without a group |
| `streams.external`, `streams.external.retry.1` to `.6` | the router's `EXTERNAL` handler; Delivery, for a retry | group `delivery` |
| `domain.events.<type>` | the outbox relay | the router's subscription cache, without a group |
| `<topic>.<group>.dlq` | a group, for a message it gave up on | operators, through DLQ replay |
| pub/sub `streams.live.<workspace>` and `tasks.live.<task>` | the router and events view; model and tool activities | open events pages and task feeds; nothing is kept |

The broker keeps a topic's entries for 72 hours: long enough to ride out a
consumer outage. Dead letters are kept for 14 days. The history you read
comes from Postgres, not from the broker.

**One stream, one partition.** A stream's events go to
`streams.events.<crc32(stream_id) mod AGENTAREA_EVENT_PARTITIONS>`, 16
partitions by default. All events of one stream are on one partition, so each
group sees them in the order they arrived. The router and the events view read
every partition in one call. No topic is created per stream, and no topic has
to be discovered.

**Intake publishes and answers.** A webhook that passes its source's checks
is named and keyed by its catalog entry. Its id is deterministic,
`uuid5(stream, event key)`, so a redelivery from the provider is the same event.
It is published to its partition and answered `202` before anything reacts.
A source that is polled is fetched by the Go event-service. It publishes each
raw item to `streams.ingest`, and the `ingest` group runs the item through the
same naming and keying as a webhook.

**The router reacts.** The `router` group keeps every stream's subscriptions
in memory. It reloads a stream's subscriptions when the outbox relay announces
a change on `domain.events.streams.subscriptions.changed`. For each event it
runs every subscription whose filter admits the event:

- a `trigger` subscription starts or continues a task;
- a `forward` copies the event into its output streams, one causation step
  deeper;
- an `external` subscription hands the event to Delivery for an MCP Events
  subscriber.

Before it acts, the router reads the subscription again, so a cached
subscription that was deleted or paused never fires. Each reaction is
recorded in `trigger_executions` before the message is acknowledged. A
redelivered event finds its recorded reactions and runs only the rest. An
event received before a subscription started is recorded as skipped with that
reason. Past `AGENTAREA_EVENT_MAX_ATTEMPTS` deliveries, the reactions still
missing are recorded as `error`, and the event moves to
`streams.events.router.dlq`.

**The events view records.** The `events-view` group writes every event into
`stream_events`, once per event id. The router writes the row itself when it
gets there first. The router also stores the routing result on the row:
when the event was routed, to how many subscriptions, and a tally of what they
did. The events page, `streams_list_events`, `read_stream` and MCP `events/poll`
all read `stream_events`. Nothing reads it to decide what to fire.

`stream_events` is partitioned by day. A day older than
`AGENTAREA_EVENT_RETENTION` (7 days by default) is dropped whole. With
`AGENTAREA_EVENT_ARCHIVE` on, the day is first written to the object store as
gzipped JSONL, one object per workspace at
`event-archive/<workspace>/<YYYY-MM-DD>.jsonl.gz`. A day the store does not
take is kept, logged as an error, and tried again on the next hourly pass.

Readers page a stream oldest first by `sequence`. A sequence is taken when a
row is inserted but becomes visible when the transaction commits. For this
reason every insert holds an advisory lock on its stream until its transaction
ends, so inserts into one stream commit in sequence order. A cursor never
passes a row that has yet to commit.

**The platform stream.** The `platform` group reads `tasks.events` and writes
each task outcome into the workspace's `platform` stream: completed, failed,
cancelled, waiting for an approval, waiting for input. Triggers subscribe to it
like any other stream. A trigger never reacts to an event that comes from a
task it started, and a firing deeper than `AGENTAREA_EVENT_FORWARD_DEPTH` is
skipped.

**Delivery sends.** The `delivery` group on `tasks.events` sends each task
event to where its task replies: the chat or mailbox it came from, the
caller's task webhook, A2A push configs. Each target is retried on its own,
so one provider that is down holds back nothing else. The same group on
`streams.external` sends stream events to MCP Events webhook subscribers with
Standard Webhooks signatures. A failed send waits on the retry topic of its
next attempt. Each retry topic has one fixed delay: 30 s, 2 min, 10 min,
30 min, 1 h, 2 h. Past the last retry the subscriber is marked `failed`.

**MCP Events, out and in.** The AgentArea MCP server serves the MCP Events
extension on every mount. Each stream you can read is an event type named
`<workspace>/<stream id>`. `events/poll` reads `stream_events` from a cursor,
and `events/subscribe` registers an `external` subscription. Going the
other way, a source of the `mcp_events` catalog entry reads the events of an
MCP server instance that offers them, through the mcp-manager gateway. A poll
source is polled by the Go event-service, and its items enter through
`streams.ingest` like any other polled source. For a webhook source, the
event-service calls `events/subscribe` with the source's URL and issued
`whsec_` secret, records the grant in `stream_sources`, and subscribes again
before the grant runs out. The server's deliveries arrive at
`/webhooks/{webhook_id}` and go through webhook intake straight to the stream's
partition. A `gap` notice becomes a `source.gap` event. A `terminated` notice
clears the subscription, and the event-service subscribes again. After a
failed attempt the next one waits: the wait starts at
`AGENTAREA_EVENT_POLL_INTERVAL`, doubles after each failure up to 1 hour, and
the wait and the error are kept on the source row.

**The events page.** `/events` reads `stream_events`, newest first. While the
page is open, it listens on `GET /v1/workspaces/{workspace}/streams/events/live`.
Each API process holds one pub/sub connection to `streams.live.<workspace>`.
The router and events view publish a notice there after each write, and the API
reads the event back under the viewer's filters and the streams they may read.

**Consumers come and go.** A process joins a group under a new consumer name
each time it starts. When a group's runtime starts, and on every reclaim pass,
the broker removes that group's consumers that hold no pending messages and
have been idle for 10 minutes. The check and the removal run as one server
script, so a consumer that reads in between cannot lose a message.
A consumer that still holds messages is left alone. Reclaim moves its messages
to a live consumer once they have been idle past the group's threshold.

## Why not a journal in Postgres

The first version of event streams kept the log in Postgres. Each subscription
had its own cursor, and a worker dispatcher claimed due subscriptions with
leases, polled on a timer, and woke on a Redis signal. It worked, but it
rebuilt every queue feature by hand: positions, leases, backoff, a retry cap,
dead letters. Every new reader, such as Delivery or the platform stream,
meant another dispatcher.

A broker's consumer groups already do all of that. The cost is that state is
now in two places: the broker holds what is in flight, and Postgres holds what
happened. A reader that needs history reads Postgres, never the broker.

A topic per stream was rejected for the same reason. It needs topics created at
runtime and a scan to find them. A fixed set of partitions keyed by stream id
keeps each stream in order with a bounded number of keys. The layout maps
one to one onto Kafka partitions.

## Limits

- **At least once, not exactly once.** Every group can see a message twice
  after a crash. Reactions are recorded by (subscription, event) and the read
  model by event id, so a repeat finds its earlier result. A webhook or channel
  send that succeeded just before a crash can still be sent again.
- **The broker keeps 72 hours.** A group that is down longer than that misses
  what the broker trimmed in the meantime. The read model then holds only what
  the events view wrote before the outage.
- **Order holds within a stream, not across streams.** Two streams on
  different partitions are processed independently. Inserts into one stream
  are serialized for the length of their short transactions.
- **Live notices are at most once.** A page that misses a notice (a lagging
  connection, an API restart) ends its stream and reads the page again. The
  workspace feed paged with `before` can miss a row that commits late. That row
  still arrives through its notice.
- **Changing `AGENTAREA_EVENT_PARTITIONS` moves streams between partitions.**
  Drain the `router` and `events-view` groups first, or a stream's old and new
  events can be handled out of order.
- **The archive is write-only.** Archived days are not readable through the
  API or MCP, and nothing restores them into `stream_events`. Archive objects
  are not deleted when a workspace is deleted.
- **An MCP Events webhook does not replay.** A subscriber that wants what it
  missed polls with its cursor, within `AGENTAREA_EVENT_RETENTION`.

## Related

<Columns cols={2}>
  <Card title="Event streams" icon="lightbulb" href="/concepts/integration/event-streams">
    Streams, sources and subscriptions.
  </Card>
  <Card title="Subscribe over MCP Events" icon="plug" href="/guides/triggers/subscribe-to-a-stream-over-mcp-events">
    Poll a stream or receive signed webhooks.
  </Card>
  <Card title="Collect events into a stream" icon="plug" href="/guides/triggers/collect-events-into-a-stream">
    Add a source to a stream.
  </Card>
  <Card title="Task events" icon="lightbulb" href="/concepts/execution/events">
    The task feed carried on `tasks.events`.
  </Card>
</Columns>
