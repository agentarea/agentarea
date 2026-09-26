---
title: Create and configure an agent
type: guide
description: "Create an agent, bind it to a model instance, and give it instructions and tools."
prerequisites:
  - /concepts/agents/what-is-an-agent
related:
  - /guides/tasks/start-a-task
  - /guides/agents/attach-skills
  - /concepts/agents/context-strategies
  - /concepts/integration/mcp
last_updated: 2026-09-07
---

An agent is stored configuration: instructions, one model instance, and the
tools and skills attached to it. Creating one does not start anything — an agent
only runs when a task is submitted against it.

Do this through the API when you are scripting or testing. The dashboard at
`/agents` does the same thing with a form.

## Prerequisites

<Info>
- A running platform — see [Run AgentArea locally](/quickstart).
- A provider configured and a **model instance** created — see
  [choose a model](/guides/agents/choose-a-model). An agent references a model
  instance, never a provider or a bare model name.
- An access token. All `/v1` endpoints below require authentication.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Find a model instance">
    ```bash
    curl -s http://localhost:8000/v1/workspaces/{workspace}/model-instances/ \
      -H "Authorization: Bearer $TOKEN"
    ```

    Note the `id` you want. This is the only hard dependency an agent has — a task
    against an agent whose model cannot be resolved fails at startup rather than
    falling back to another model.
  </Step>

  <Step title="Create the agent">
    Only `name` is required. Everything else has a default or is optional.

    ```bash
    curl -X POST http://localhost:8000/v1/workspaces/{workspace}/agents/ \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "release-notes",
        "description": "Summarises merged pull requests into release notes",
        "instruction": "You write release notes. Group changes by area, lead with user-visible behaviour, and omit refactors that change nothing observable.",
        "model_id": "<model-instance-id>"
      }'
    ```

    | Field | Meaning |
    |---|---|
    | `name` | Required. A slug is derived from it and is unique per workspace. |
    | `instruction` | The system prompt. |
    | `model_id` | The model **instance** id from step 1. |
    | `description` | Shown in listings; also what other agents see when this one is exposed as a tool. |
    | `agent_type` | Defaults to `stateless`. |
    | `tools` | Attached tools and their configuration. |
    | `skill_ids` | Skills to attach — see [attach skills](/guides/agents/attach-skills). |
    | `planning` | Runs the planning activity before execution. |
    | `a2ui_enabled` | Lets the agent drive interactive UI surfaces. |
    | `events_config` | Which events the agent emits or reacts to. |
  </Step>

  <Step title="Attach tools">
    Tools reach an agent from five places — built-in toolsets, MCP servers, code
    tools, other agents, and OpenAPI connections. Attaching an MCP server is the
    common case and is covered in
    [add a hosted MCP server](/guides/mcp/add-a-hosted-server).

    What the model is actually shown at each turn is narrower than what is attached:
    the resolved policy filters the list before the model sees it, and a denied tool
    is never offered. See [tool authorization](/concepts/governance/tool-authorization).
  </Step>

  <Step title="Choose a context strategy">
    Leave this alone unless you have a reason. The default is `hybrid`, resolved as
    `agent override > model default > hybrid`.

    | Strategy | Tools | Large tool output |
    |---|---|---|
    | `static` | all loaded up front | kept inline |
    | `hybrid` | all loaded up front | offloaded to object storage |
    | `dynamic` | catalog plus an activation tool | offloaded |

    Use `dynamic` when the attached tool set is large enough to crowd the context
    window. See [context strategies](/concepts/agents/context-strategies).
  </Step>
</Steps>

## Verify

Run a task and watch it reach a terminal event:

```bash
curl -X POST http://localhost:8000/v1/workspaces/{workspace}/agents/<agent-id>/tasks/sync \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Say hello and stop."}'
```

`/sync` blocks until the task finishes, which makes it the fastest way to tell a
misconfigured agent from a working one. For the streaming and scheduled variants
see [start a task](/guides/tasks/start-a-task).

## Troubleshooting

<AccordionGroup>
  <Accordion title="The task fails immediately with `InvalidExecutionSnapshot`">
    The agent's model spec has no positive `context_window` . There is no
    default; the platform refuses to run against a guessed window.
  </Accordion>
  <Accordion title="The task fails with a missing-limits error">
    A task needs a complete runtime policy — run budget, token ceilings, turn
    and tool-call limits — before it may start. New workspaces are seeded with
    defaults; a workspace whose rules were edited may be missing one. See
    [policy syntax](/reference/policy-syntax) .
  </Accordion>
  <Accordion title="The agent ignores a tool you attached">
    Check whether policy denies it. A denied tool is filtered out at disclosure,
    so the model never sees it and cannot report that it is missing.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="What is an agent" icon="robot" href="/concepts/agents/what-is-an-agent">
    An agent is a workspace-scoped definition
  </Card>
  <Card title="Start a task" icon="list-check" href="/guides/tasks/start-a-task">
    Launch an agent run over REST, the CLI, or A2A
  </Card>
  <Card title="Attach skills" icon="robot" href="/guides/agents/attach-skills">
    Create or import a skill and attach it to an agent so it is offered at
    runtime
  </Card>
  <Card title="Set a budget" icon="scale-balanced" href="/guides/governance/set-a-budget">
    Cap monthly spend, per-run spend, service spend or tokens for a workspace,
    agent, user or single
  </Card>
</Columns>
