---
title: Trigger an agent from a webhook
type: guide
description: "Give an external system a URL that starts an agent task, and verify the requests that arrive on it."
prerequisites:
  - /concepts/integration/triggers
related:
  - /guides/triggers/schedule-an-agent
  - /concepts/integration/triggers
  - /concepts/integration/event-streams
  - /guides/tasks/debug-a-failed-task
  - /reference/errors
last_updated: 2026-10-06
---

A webhook trigger turns an agent into an endpoint: something posts to a URL, and
a task starts. This guide creates one, secures it, and shows how to tell a
rejected delivery from a filtered one.

A delivery is recorded first and answered immediately; the task it produces,
if any, starts moments later when the dispatcher next reaches that event — not
inline with the HTTP response. See [Event
streams](/concepts/integration/event-streams) for what happens in between.

## Prerequisites

<Info>
- An agent with a working model. See [create and configure an agent](/guides/agents/create-and-configure).
- A publicly reachable API, or a tunnel to your local one — the sending system
  has to be able to reach the webhook URL.
- An access token as `AGENTAREA_TOKEN` and the API base URL as `AGENTAREA_URL`.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Create the trigger">
    Omit `webhook_id` and the platform generates one with
    `secrets.token_urlsafe(16)`. Let it — a generated id is unguessable, and for
    an unverified webhook the URL is the only thing standing between the agent
    and the internet.

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "triage-github-issues",
        "agent_id": "<agent-id>",
        "trigger_type": "webhook",
        "webhook_type": "github",
        "allowed_methods": ["POST"],
        "event_types": ["issues"],
        "task_parameters": {
          "description": "Triage this issue and label it."
        },
        "failure_threshold": 3
      }'
    ```

    | Field | Meaning |
    |---|---|
    | `webhook_type` | Selects the signature verifier. Defaults to `generic`. Unknown strings are accepted, not rejected. |
    | `webhook_id` | The path segment of the URL. Generated when omitted. |
    | `allowed_methods` | Defaults to `["POST"]`. A request with another method is rejected before anything else runs. |
    | `event_types` | Provider event names this trigger cares about. |
    | `validation_rules` | Signature configuration, plus request-shape checks. |
    | `conditions` | Evaluated after validation, before a task is created. Model-evaluated unless you set an explicit `type`. |

    The response carries both `webhook_id` and `webhook_url` — the full
    address, ready to give the sending system:

    ```text
    POST {AGENTAREA_URL}/webhooks/{webhook_id}
    ```

    A request there is recorded in the trigger's own [event
    stream](/concepts/integration/event-streams) before anything else happens.
  </Step>

  <Step title="Turn on signature verification">
    <Warning>
    Verification is **opt-in for every type**, including `github` and `stripe`.
    Without a signing secret, `verify_webhook_signature` returns "not enabled"
    and the request proceeds unverified. Naming a `webhook_type` alone secures
    nothing.
    </Warning>

    Configure the secret the provider signs with, then point the trigger at it:

    ```bash
    curl -X PUT "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/$TRIGGER_ID" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"webhook_config": {"signing_secret": "<the provider'\''s secret>"}}'
    ```

    For `generic` webhooks the HMAC details are configurable, because the sender
    is whatever you wrote:

    ```json
    {
      "validation_rules": {
        "signature_header": "x-webhook-signature",
        "signature_algorithm": "sha256",
        "signature_prefix": ""
      }
    }
    ```

    Those three values are the defaults. `signature_algorithm` is one of `sha1`,
    `sha256`, `sha384` or `sha512`; any other value is refused with 422 when the
    trigger is saved. `slack`, `github`, `discord` (Ed25519),
    `linear` and `stripe` ignore them and use their provider's scheme. Telegram
    is validated by bot token at a different layer.
  </Step>

  <Step title="Point the sending system at the URL">
    Register the URL wherever the events come from — a GitHub repository webhook,
    a Stripe endpoint, your own service.

    <Note>
    Only Telegram registers its inbound webhook with the provider automatically.
    Every other channel is a manual step, and nothing in the platform reports
    that you skipped it.
    </Note>
  </Step>

  <Step title="Send a test delivery">
    Use the provider's own "redeliver" or "send test" button where one exists —
    it exercises the real signature path, which a hand-rolled `curl` does not.

    For a `generic` webhook with no secret configured yet:

    ```bash
    curl -i -X POST "$AGENTAREA_URL/webhooks/$WEBHOOK_ID" \
      -H "Content-Type: application/json" \
      -d '{"action": "opened", "issue": {"title": "Crash on startup"}}'
    ```

    A request that passes method, signature, and size checks gets `202` back
    immediately:

    ```json
    {"status": "accepted", "sequence": 42}
    ```

    The same request repeated with the same provider delivery id (GitHub's
    `X-GitHub-Delivery`, Stripe's `id`, a `webhook-id` or `Idempotency-Key`
    header, and a few others) gets `202` again with `"status": "duplicate"`
    and the same `sequence`, instead of a second row and a second task. A
    provider with none of those is never deduplicated — every delivery gets a
    fresh `sequence`. A burst over `AGENTAREA_EVENT_WRITE_QUOTA` gets `429`; a
    body over 256 KiB gets `413`.
  </Step>
</Steps>

## Verify

The trigger's execution history records every delivery that actually reached
condition evaluation, including ones that produced no task:

```bash
curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/$TRIGGER_ID/executions" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.[0] | {status, task_id, error_message}'
```

<Check>
`status: "success"` with a `task_id` means the delivery started a task. `status:
"success"` with `task_id: null` means validation passed and the conditions
declined — the trigger is working and deliberately filtering.
</Check>

A delivery rejected at the method, signature, or validation stage never becomes
an execution record with a task — check the API logs for the rejection reason,
which is deliberately not returned to the caller in detail. Three other things
also never become an execution record, because the dispatcher stops them
before `TriggerService` ever evaluates conditions: an event filtered out by
`event_types`, a trigger that is paused or disabled, and a configurer who lost
access to the agent. All three still show up as the stream's own record — read
`stream_id` off the trigger (`GET .../triggers/$TRIGGER_ID` returns it), then:

```bash
curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/streams/$STREAM_ID/events?limit=1" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.events[0] | {sequence, kind, outcomes}'
```

`outcomes` is empty when no subscription's filter matched the event at all;
otherwise it carries a `verdict` (`reacted`, `skipped`, `error`) and `reason`
per subscription, independent of whether a task execution record exists. The
same list, with the trigger's name and a link to any task it created, is on
the workspace's Events page.

## Troubleshooting

<AccordionGroup>
  <Accordion title="`Signature verification failed`">
    A signing secret is configured and the signature did not match. The most
    common cause is the body: the signature is computed over the exact raw bytes,
    so any proxy that re-serializes JSON between the provider and the API
    invalidates it. The same response is returned when a secret is configured but
    the raw body was unavailable to verify.
  </Accordion>
  <Accordion title="`Method ... not allowed`">
    `allowed_methods` defaults to `["POST"]` and is checked before signature and
    validation. A provider that sends `PUT`, or a browser preflight, is rejected
    here.
  </Accordion>
  <Accordion title="The delivery was accepted (`202`) but no task appears">
    Check the stream's events (see [Verify](#verify)) before assuming a bug —
    three different things look like this and each has a different cause:

    - **The conditions declined.** Conditions with no explicit `type` are
      evaluated by a model against the payload once the dispatcher reaches the
      event, so the verdict is a judgement, not a rule mismatch. The
      execution record exists; read `trigger_data` on it, or `reason` on the
      stream's outcome, to see exactly what the model was shown.
    - **`event_types` filtered it out.** The subscription only sees the kinds
      it names; an event of any other kind gets no outcome at all for this
      trigger, and no execution record — "nobody listened," not a failure.
    - **The trigger is paused or disabled.** The event is still recorded and
      the dispatcher still reaches it, but a trigger whose `is_active` is
      false is skipped before conditions are ever evaluated — no execution
      record, only a `skipped` outcome on the stream.
  </Accordion>
  <Accordion title="The webhook keeps answering `202`, but the trigger stopped firing">
    Crossing `failure_threshold` consecutive failures disables the trigger —
    but it does not touch the webhook source. Deliveries are still recorded
    and still answered `202`; only the firing is skipped. Nothing re-enables
    the trigger automatically:

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/$TRIGGER_ID/enable" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```

    Re-enabling does not replay what was skipped while it was off — only
    events the dispatcher reaches from then on fire.
  </Accordion>
  <Accordion title="`429` on a burst of deliveries">
    The workspace crossed `AGENTAREA_EVENT_WRITE_QUOTA` events in the trailing
    minute — counted across every stream the workspace owns, not just this
    one, so a quiet second stream does not help. A provider's own retry
    handles an occasional `429`; a sustained one means the deployment's
    `AGENTAREA_EVENT_WRITE_QUOTA` needs raising. See
    [Configuration](/self-host/configuration).
  </Accordion>
  <Accordion title="`413 Payload Too Large`">
    The request body is over 256 KiB after headers and query parameters that
    look like credentials are stripped. Send a reference to a workspace file
    instead of the content itself.
  </Accordion>
  <Accordion title="I set `webhook_type` and assumed it was secured">
    It is not. The type selects *which* verifier runs, not *whether* one runs.
    Verification begins only once a signing secret resolves from
    `webhook_config` or `validation_rules`.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Triggers and channels" icon="plug" href="/concepts/integration/triggers">
    The model behind this, and what it does not cover.
  </Card>
  <Card title="Event streams" icon="plug" href="/concepts/integration/event-streams">
    The journal a delivery lands in, and who else can read it.
  </Card>
  <Card title="Schedule an agent" icon="plug" href="/guides/triggers/schedule-an-agent">
    The other way a task starts without a person.
  </Card>
  <Card title="Debug a failed task" icon="list-check" href="/guides/tasks/debug-a-failed-task">
    When the delivery worked and the task did not.
  </Card>
  <Card title="Errors" icon="book" href="/reference/errors">
    What the API returns, and what is safe to retry.
  </Card>
</Columns>
