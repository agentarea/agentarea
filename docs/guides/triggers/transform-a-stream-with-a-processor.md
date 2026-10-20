---
title: Transform a stream with a processor
type: guide
description: "Have an agent write a Python processor that reads each event of a stream and writes new events into other streams, run by the platform in the sandbox."
prerequisites:
  - /concepts/integration/event-streams
  - /guides/triggers/collect-events-into-a-stream
related:
  - /concepts/integration/event-streams
  - /guides/triggers/collect-events-into-a-stream
  - /guides/triggers/trigger-from-a-webhook
last_updated: 2026-10-19
---

A processor is a short Python function that turns the events of one stream
into events of other streams: keep only the large orders, split a mixed feed
by kind, reshape a provider's payload. An agent writes it with the streams
tools; the platform runs it over every matching event in the sandbox. Use a
processor when a rule decides where an event goes. When an agent should
reason about each event, attach a [trigger](/guides/triggers/trigger-from-a-webhook)
instead; to copy events unchanged, a forward is enough.

<Info>
**Prerequisites**

- An input stream with events in it, and the output streams created: see
  [Collect events into a stream](/guides/triggers/collect-events-into-a-stream).
- An agent with the `agentarea/streams` toolset, or a member who may edit the
  input stream and every output stream.
</Info>

## The contract

The code defines `process(event: dict) -> list[dict] | None`.

- `event` holds `id`, `kind`, `key`, `data`, `source_type`, `session_key`,
  `sender`, `subject`, `time`, `received_at`, `correlation_id`,
  `causation_id`, `depth`, `stream_id` and `attachments`. `data` is what the
  source delivered; a webhook's JSON body is `data["body"]`.
- Each dict returned is one event to write: `{"stream", "kind", "data", "key"}`.
  `stream` is the id or name of one of the processor's output streams; `key`
  is optional. Return `None` or `[]` to drop the event. A single dict is an
  error, not one event.

```python
def process(event):
    order = event["data"]["body"]
    if event["kind"].startswith("order.") and order.get("amount", 0) > 100:
        return [{"stream": "big-orders", "kind": event["kind"], "data": order}]
    return None
```

## Steps

<Steps titleSize="h3">
  <Step title="Ask an agent to write it">
    Give the agent the input stream, the output streams and the rule. It calls
    `streams_create_processor` with `stream_id`, `output_stream_ids`, `code` and
    an optional `event_filter` (`{"kinds": ["order"]}` runs the code only on
    `order.*` events). A good agent reads a recent event with
    `streams_list_events` first, to see the shape of `data`.
  </Step>
  <Step title="Or create it over REST">
    `POST /v1/workspaces/{workspace}/streams/{stream_id}/processors` with the
    same fields. `PATCH .../processors/{subscription_id}` changes the code,
    outputs or filter; `DELETE` removes it. The events it already wrote stay.
  </Step>
  <Step title="Post events">
    Every event that matches the filter runs the code once. What it returns is
    appended to the output streams, each event with `causation_id` set to the
    event it came from, the same `correlation_id`, and one more `depth`.
  </Step>
</Steps>

## Verify

Open the input stream in **Events**. The **Processors** panel lists each
processor with its outputs and its code. In the feed, select an event: the
processor's handler says **Reacted** with the events it wrote, **Skipped**
with `process() wrote no events`, or **Error** with the exception and its line,
for example `ZeroDivisionError: division by zero (processor.py line 3)`. The
output stream shows the new events, linked back to their cause.

## Limits

- Each run has 10 seconds and may return up to 100 events and 256 KiB of
  output. The event and the code together must fit in 256 KiB.
- The code gets no secrets. Code that holds something that looks like a key,
  token or password is refused when it is saved, because everyone who can
  read the stream sees it.
- Network access is whatever the deployment's sandbox policy gives an agent's
  shell; the processor gets no more.
- A processor never writes into its own input stream: that is refused when it
  is created or changed, and checked again on every run. A chain of
  processors and forwards stops at `AGENTAREA_EVENT_FORWARD_DEPTH`.
- A stream a processor writes into cannot be deleted until the processor is.

## Troubleshooting

<AccordionGroup>
  <Accordion title="Every event is skipped">
    The code looks for a field where the source does not put it. Read one event
    with `streams_list_events` and compare its `data` with what the code reads.
  </Accordion>
  <Accordion title="An error reaction on every event">
    The reason names the problem: an exception with its line, a result that is
    not a list, or a `stream` that is not one of the outputs. Fix the code with
    `streams_update_processor`; the next event runs the new code. A failed
    event is not run again.
  </Accordion>
  <Accordion title="Events wait, then fail with the delivery limit">
    The sandbox could not run the code at all. The event is redelivered, and
    after `AGENTAREA_EVENT_MAX_ATTEMPTS` deliveries it is recorded as an error
    and dead-lettered. Check that the sandbox service is up.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Event streams" icon="lightbulb" href="/concepts/integration/event-streams">
    How streams, subscriptions and the router fit together
  </Card>
  <Card title="Collect events into a stream" icon="plug" href="/guides/triggers/collect-events-into-a-stream">
    Add a webhook or poll source to a stream
  </Card>
</Columns>
