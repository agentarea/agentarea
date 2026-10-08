---
title: Collect events into a stream
type: guide
description: "Point Sentry, GitHub or YooKassa at a stream with no trigger, then have a weekly agent read what arrived with read_stream."
prerequisites:
  - /concepts/integration/event-streams
related:
  - /concepts/integration/event-streams
  - /guides/triggers/schedule-an-agent
  - /guides/triggers/trigger-from-a-webhook
last_updated: 2026-10-07
---

A webhook source records every delivery it receives into a stream, and nothing
runs. Use it when the events are material for later — a weekly error digest, a
payments summary — rather than something an agent must act on as each one
arrives. When each event should start a run, create a
[webhook trigger](/guides/triggers/trigger-from-a-webhook) instead.

## Prerequisites

<Info>
- An access token, exported as `AGENTAREA_TOKEN`, the API base URL as
  `AGENTAREA_URL`, and your workspace slug as `WORKSPACE`.
- Edit access to the stream. Adding or deleting a source is checked as `edit`
  on that stream.
- A public base URL for webhooks. The URL a source hands out is built from the
  same setting webhook triggers use; a sender cannot reach `localhost`.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Create the stream">
    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "sentry-errors", "retention_days": 30}'
    ```

    Note the `id`. `retention_days` is how long events stay readable; leave it
    out to take the deployment's default.
  </Step>

  <Step title="Store the provider's secret">
    A source never holds a secret. It refers to a workspace secret, and the
    value is read from there each time a delivery is verified, so rotating the
    secret needs no change to the source.

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/secrets" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "sentry-client-secret", "value": "<client secret>"}'
    ```

    Note the secret's `id`. On the stream's page in the web app, the **Add
    source** dialog can create the secret for you from the same picker.
  </Step>

  <Step title="Add the source">
    `GET /v1/workspaces/{workspace}/streams/source-types` lists every type with
    the credentials and settings it needs. Pass each credential as
    `{"secret_id": ...}`:

    <Tabs>
      <Tab title="Sentry">
        ```bash
        curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/$STREAM_ID/sources" \
          -H "Authorization: Bearer $AGENTAREA_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"webhook_type": "sentry",
               "credentials": {"client_secret": {"secret_id": "<secret-id>"}}}'
        ```

        In Sentry, open **Settings → Developer Settings → Custom
        Integrations**, create an **Internal Integration**, paste the
        `webhook_url` from the response as its Webhook URL, and tick the
        resources to send (Issue, Error, Comment). The integration's **Client
        Secret** is the value you stored. Sentry signs each body with it into
        `Sentry-Hook-Signature`; the event is named from `Sentry-Hook-Resource`
        and the body's `action`, so an issue created arrives as
        `issue.created`.
      </Tab>
      <Tab title="GitHub">
        ```bash
        curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/$STREAM_ID/sources" \
          -H "Authorization: Bearer $AGENTAREA_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"webhook_type": "github",
               "credentials": {"webhook_secret": {"secret_id": "<secret-id>"}}}'
        ```

        In the repository, open **Settings → Webhooks → Add webhook**. Set
        **Payload URL** to the `webhook_url`, **Content type** to
        `application/json`, and **Secret** to the value you stored. Events are
        named `<X-GitHub-Event>.<action>`, such as `pull_request.opened`, and a
        redelivery is recognized by `X-GitHub-Delivery`.
      </Tab>
      <Tab title="YooKassa">
        ```bash
        curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/$STREAM_ID/sources" \
          -H "Authorization: Bearer $AGENTAREA_TOKEN" \
          -H "Content-Type: application/json" \
          -d '{"webhook_type": "yookassa",
               "credentials": {"secret_key": {"secret_id": "<secret-id>"}},
               "config": {"shop_id": "<shop id>"}}'
        ```

        The stored secret is the shop's API secret key (`live_…` or
        `test_…`). In the YooKassa merchant profile, open **Integration →
        HTTP notifications**, paste the `webhook_url`, and pick the events.
        YooKassa does not sign notifications, so each one is checked against
        its API instead: AgentArea reads the notified object back with your
        shop id and key and records the event only when YooKassa answers that
        object in the notified state. The event is named by the body's
        `event` (`payment.succeeded`), and a repeat of the same object reaching
        the same state is recorded once.
      </Tab>
    </Tabs>

    The response carries `webhook_url`. A source creation that lacks a
    credential its verifier needs is refused with `422` — a source is never
    created unverified. The `generic` and `email` types take an optional
    signing secret: leave it out and one is issued, returned once as
    `signing_secret` together with the `signature_scheme` to sign with.
  </Step>

  <Step title="Give an agent read_stream">
    Attach the `agentarea/stream_events` toolset to the agent that will read
    the stream:

    ```json
    "tools": [{"type": "code", "name": "agentarea/stream_events"}]
    ```

    Its one tool, `read_stream(stream, after_sequence, limit)`, takes the
    stream's name or id and returns up to `limit` events (1–200) after
    `after_sequence`, oldest first, with `next_after` and `has_more`. It reads
    only streams of the agent's workspace that the run's user may read, strips
    credential headers from each event's `data`, and marks the data as
    untrusted input from outside senders.
  </Step>

  <Step title="Schedule the read">
    A cron trigger runs the agent weekly. The platform keeps no cursor for the
    agent, so choose where `next_after` lives:

    - **The retention window.** Give the stream a `retention_days` equal to the
      period, and have the agent read from `0`, passing `next_after` back while
      `has_more` is true. Each run sees what the stream still holds.
    - **A cursor the agent keeps.** If the agent can write somewhere durable —
      a note in a system it reaches through an MCP server, for example — have
      it store `next_after` at the end of a run and pass it as
      `after_sequence` the next time, which returns exactly what is new.

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "weekly-sentry-digest",
        "agent_id": "<agent-id>",
        "trigger_type": "cron",
        "cron_expression": "0 9 * * 1",
        "timezone": "Europe/Moscow",
        "task_parameters": {
          "text": "Call read_stream on sentry-errors from after_sequence 0, then again with next_after while has_more is true. Summarise the new and resolved issues of the past week."
        }
      }'
    ```
  </Step>
</Steps>

## Verify

Send a test delivery from the provider (GitHub: **Recent Deliveries →
Redeliver**; Sentry: the integration's test button; YooKassa: a test payment in
a `test_` shop). The provider sees `202` with `{"status": "accepted",
"sequence": n}`, and the event appears on the stream's page under **Events**.
List the sources to see what feeds the stream:

```bash
curl "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/$STREAM_ID/sources" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

No credential is ever returned here; a source added directly has
`trigger_id: null`.

## Troubleshooting

- **`400 Signature verification failed`.** The secret stored is not the one
  the provider signs with — for Sentry it must be the integration's Client
  Secret, for GitHub the webhook's Secret. For YooKassa it means the API did
  not confirm the object: a wrong shop id or key, a `test_` key against a live
  shop, or the object already moved on to another status.
- **`400 Webhook … not found`.** The source was deleted; its URL stops
  answering. Add a new source and give the sender the new URL.
- **`409` when deleting a source or the stream.** A webhook trigger owns that
  source. Delete the trigger, not the source.
- **`read_stream` returns an error naming the stream.** The name is not a
  stream of the agent's workspace, or the run's user cannot read it.

## Related

<Columns cols={2}>
  <Card title="Event streams" icon="diagram-project" href="/concepts/integration/event-streams">
    How a stream records, deduplicates and fans out events.
  </Card>
  <Card title="Schedule an agent" icon="clock" href="/guides/triggers/schedule-an-agent">
    Cron triggers, their limits, and how to confirm one fired.
  </Card>
</Columns>
