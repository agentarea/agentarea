---
title: Schedule an agent
type: guide
description: "Run an agent on a cron schedule, confirm it fired, and stop it running away."
prerequisites:
  - /concepts/integration/triggers
related:
  - /guides/triggers/trigger-from-a-webhook
  - /guides/tasks/debug-a-failed-task
  - /concepts/integration/triggers
  - /guides/governance/set-a-budget
last_updated: 2026-09-13
---

A cron trigger starts a task on a schedule with no one present. This guide
creates one, proves it fired, and sets the limits that keep an unattended agent
from running away.

## Prerequisites

<Info>
- An agent with a working model — a scheduled task against a misconfigured agent
  fails on every tick. See [create and configure an agent](/guides/agents/create-and-configure).
- A running Temporal worker. Cron triggers are Temporal schedules; without a
  worker the schedule fires and nothing picks it up.
- An access token, exported as `AGENTAREA_TOKEN`, and the API base URL as
  `AGENTAREA_URL`.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Create the trigger">
    `agent_id`, `name`, and `trigger_type` are the only required fields.
    `cron_expression` is required in practice for a cron trigger — creation is
    rejected without it.

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/triggers/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "daily-release-notes",
        "description": "Summarise yesterday'\''s merged pull requests",
        "agent_id": "<agent-id>",
        "trigger_type": "cron",
        "cron_expression": "0 9 * * 1-5",
        "timezone": "Europe/Amsterdam",
        "task_parameters": {
          "description": "Summarise the pull requests merged yesterday."
        },
        "failure_threshold": 3
      }'
    ```

    | Field | Meaning |
    |---|---|
    | `cron_expression` | Standard five-field cron. Interpreted in `timezone`, not UTC. |
    | `timezone` | IANA name. Defaults to `UTC` — set it explicitly if the schedule is meant to track office hours. |
    | `task_parameters` | Merged into every task this trigger creates. This is where the agent's actual instruction goes. |
    | `failure_threshold` | Consecutive failures before the trigger disables itself. Defaults to `5`, bounded 1–100. |
    | `conditions` | Optional gate evaluated before a task is created. Defaults to model-evaluated — see [triggers](/concepts/integration/triggers). |
    | `enabled` | Defaults to `true`. Create it `false` to wire it up before it starts firing. |

    <Note>
    The schedule is registered in Temporal as `cron-trigger-<trigger_id>`, so it
    also appears in the Temporal UI and can be paused there. Pausing it there
    does not update the trigger record — prefer the API below.
    </Note>
  </Step>

  <Step title="Fire it once, without waiting for the schedule">
    Do not wait until 09:00 to find out the agent's model is unset.

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/triggers/$TRIGGER_ID/execute" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```

    This runs the same path the schedule runs, including conditions, and records
    a `TriggerExecution` exactly as a scheduled tick would.
  </Step>

  <Step title="Put a ceiling on it">
    A schedule multiplies whatever one run costs. An agent that costs a little
    and runs hourly costs a lot by the end of the month, and nobody is watching
    at 03:00.

    Set the budget on the agent or the workspace rather than on the trigger —
    the trigger has no budget of its own. See
    [set a budget](/guides/governance/set-a-budget).

    <Warning>
    If the trigger uses the default model-evaluated `conditions`, every candidate
    event pays for an inference *before* a task exists, so that spend is not
    attributed to the agent's task budget.
    </Warning>
  </Step>
</Steps>

## Verify

Read the execution history. This is the record of what the schedule actually
did, including ticks that created no task:

```bash
curl -s "$AGENTAREA_URL/v1/triggers/$TRIGGER_ID/executions" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" | jq '.[0]'
```

```json
{
  "trigger_id": "…",
  "executed_at": "2026-09-13T09:00:02.117Z",
  "status": "success",
  "task_id": "…",
  "execution_time_ms": 341,
  "workflow_id": "task-…",
  "run_id": "…",
  "error_message": null
}
```

<Check>
`status: "success"` with a non-null `task_id` means the tick created a task.
`status: "success"` with `task_id: null` means the trigger ran and its conditions
declined to create one — that is a working trigger, not a broken one.
</Check>

Follow `task_id` into [debug a failed task](/guides/tasks/debug-a-failed-task) if
the task itself went wrong. A trigger's job ends when the task exists.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The schedule never fires">
    Cron triggers are Temporal schedules. Check that the Temporal service is
    reachable and that a worker is running — the schedule fires into a task queue
    and a tick with no worker produces nothing. Look for
    `cron-trigger-<trigger_id>` in the Temporal UI: if the schedule is absent,
    creation did not reach Temporal; if it is present and firing, the problem is
    downstream.
  </Accordion>
  <Accordion title="It fired at the wrong hour">
    `timezone` defaults to `UTC`, not to the server's local zone or the
    workspace's. A `0 9 * * *` trigger created without `timezone` fires at 09:00
    UTC. Set an explicit IANA name.
  </Accordion>
  <Accordion title="The trigger stopped on its own">
    Crossing `failure_threshold` consecutive failures disables the trigger. That
    is the safety mechanism working. Nothing re-enables it when the cause is
    fixed — read the recent failures, fix the cause, then re-enable explicitly:

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/triggers/$TRIGGER_ID/enable" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN"
    ```
  </Accordion>
  <Accordion title="Executions are recorded but no tasks appear">
    The conditions are declining every event. A condition whose `type` is left
    unset is evaluated by a model, so its verdict is not a bug in your
    expression — read `trigger_data` on the execution record to see what the
    model was given.
  </Accordion>
  <Accordion title="A `polling` trigger does nothing">
    `polling` is accepted by the API and has no implementation behind it. Use a
    `cron` trigger with `data_extractor` for periodic fetching. See the limits in
    [triggers](/concepts/integration/triggers).
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Triggers and channels" icon="plug" href="/concepts/integration/triggers">
    Why scheduling lives in Temporal, and what a channel does.
  </Card>
  <Card title="Debug a failed task" icon="list-check" href="/guides/tasks/debug-a-failed-task">
    When the trigger worked and the task did not.
  </Card>
  <Card title="Set a budget" icon="scale-balanced" href="/guides/governance/set-a-budget">
    The ceiling an unattended schedule needs.
  </Card>
  <Card title="Durable execution" icon="diagram-project" href="/concepts/execution/durable-execution">
    The Temporal machinery underneath.
  </Card>
</Columns>
