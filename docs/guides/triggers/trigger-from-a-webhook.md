---
title: Trigger an agent from a webhook
type: guide
description: "Give an external system a URL that starts an agent task, and verify the requests that arrive on it."
prerequisites:
  - /concepts/integration/triggers
related:
  - /guides/triggers/schedule-an-agent
  - /concepts/integration/triggers
  - /guides/tasks/debug-a-failed-task
  - /reference/errors
last_updated: 2026-09-13
---

A webhook trigger turns an agent into an endpoint: something posts to a URL, and
a task starts. This guide creates one, secures it, and shows how to tell a
rejected delivery from a filtered one.

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

    The response carries the `webhook_id`. The URL is:

    ```text
    POST {AGENTAREA_URL}/webhooks/{webhook_id}
    ```
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

    Those three values are the defaults. `slack`, `github`, `discord` (Ed25519),
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
  </Step>
</Steps>

## Verify

The execution history records every delivery that reached the trigger, including
ones that produced no task:

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
an execution record with a task. Check the API logs for the rejection reason,
which is deliberately not returned to the caller in detail.

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
  <Accordion title="Deliveries return success but nothing happens">
    Validation passed and the conditions declined to create a task. Conditions
    with no explicit `type` are evaluated by a model against the payload, so the
    verdict is a judgement, not a rule mismatch. Read `trigger_data` on the
    execution record to see exactly what the model was shown.
  </Accordion>
  <Accordion title="The webhook worked and then stopped accepting anything">
    Crossing `failure_threshold` consecutive failures disables the trigger, and
    nothing re-enables it automatically:

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/$TRIGGER_ID/enable" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```
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
