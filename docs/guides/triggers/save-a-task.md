---
title: Save a task and run it again
type: guide
description: "Save what you ask an agent once, run it on demand, and point a trigger at it."
prerequisites:
  - /concepts/integration/triggers
related:
  - /guides/triggers/schedule-an-agent
  - /guides/tasks/debug-a-failed-task
  - /concepts/integration/triggers
last_updated: 2026-10-20
---

A saved task is the description of a task — the agent, what it is asked, and
the parameters — kept so it can be run again. It runs on demand, and a trigger
can point at it instead of carrying its own text. Every run records the saved
task it came from in `provenance.task_definition_id`. In the app they are under
**Saved tasks**.

## Prerequisites

<Info>
- An agent with a working model in the workspace.
- Permission to run that agent. Running a saved task is a run of its agent, so
  it needs `execute` on the agent; saving one does not.
- An access token, exported as `AGENTAREA_TOKEN`, the API base URL as
  `AGENTAREA_URL`, and the workspace slug as `WORKSPACE`.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Save the task">
    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/task-definitions/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "Release notes",
        "agent_id": "<agent-id>",
        "description": "Summarise the pull requests merged yesterday.",
        "parameters": {"model_override": "<model-id>"}
      }'
    ```

    `name` is 1–255 characters, `description` is what the agent is asked and
    must not be blank, and the agent must exist in the workspace. `parameters`
    take the same keys as a task's; `delivery_address` and `session` are
    refused, as on a task.
  </Step>

  <Step title="Run it">
    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/task-definitions/$DEFINITION_ID/run" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"parameters": {"day": "2026-10-19"}}'
    ```

    The body is optional; its `parameters` are merged over the saved ones for
    this run only. The response is the task, as `POST .../agents/{id}/tasks/sync`
    returns it. The run belongs to the caller: `provenance.origin_type` is
    `user` and `provenance.source_identity` is `user:<your id>`. A caller
    without `execute` on the agent gets `403` and nothing starts.
  </Step>

  <Step title="Point a trigger at it">
    Pass `task_definition_id` when creating or updating a trigger of the same
    agent. Each firing then asks the saved task's text with its parameters, in
    place of the trigger's own `task_parameters`, so a cron trigger needs no
    `text` of its own:

    ```bash
    curl -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/" \
      -H "Authorization: Bearer $AGENTAREA_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "daily-release-notes",
        "agent_id": "<agent-id>",
        "trigger_type": "cron",
        "cron_expression": "0 9 * * 1-5",
        "task_definition_id": "<definition-id>"
      }'
    ```

    A saved task of another agent, or of another workspace, is refused with
    `400`. Send `"task_definition_id": null` on an update to go back to the
    trigger's own text.
  </Step>
</Steps>

## Verify

Every task started from it carries the saved task's id:

```bash
curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/tasks/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  | jq '[.[] | select(.provenance.task_definition_id == "<definition-id>") | {id, status, origin: .provenance.origin_type}]'
```

<Check>
A run you started reads `origin: "user"`; one a trigger fired reads
`origin: "trigger"`, with the trigger in `provenance.origin_id`.
</Check>

## Troubleshooting

<AccordionGroup>
  <Accordion title="Deleting a saved task, or changing its agent, answers 409">
    Triggers still run it. A trigger was bound to one agent, so the saved task
    cannot move to another or disappear under it. Point those triggers at
    another saved task, or send `"task_definition_id": null` with
    `task_parameters.text`, then try again.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Schedule an agent" icon="clock" href="/guides/triggers/schedule-an-agent">
    A cron trigger, its limits, and how to check it fired.
  </Card>
  <Card title="Triggers and channels" icon="plug" href="/concepts/integration/triggers">
    What starts a task when nobody is there.
  </Card>
</Columns>
