---
title: Attach skills to an agent
type: guide
description: "Create or import a skill and attach it to an agent so it is offered at runtime."
prerequisites:
  - /concepts/agents/skills
related:
  - /guides/agents/create-and-configure
  - /concepts/agents/context-strategies
  - /concepts/integration/registry-and-catalog
last_updated: 2026-09-07
---

A skill is a named bundle of instructions and files. Attaching one does not put
its content in the prompt: the agent is offered the skill, and activating it
materialises its files into the task workspace and injects its instructions.
That is what keeps ten attached skills from costing ten skills' worth of context.

Skills are attached many-to-many, so the same skill serves several agents and is
maintained once.

## Prerequisites

<Info>
- An agent — see [create and configure an agent](/guides/agents/create-and-configure).
- An access token.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Get a skill">
    Create one from inline content:

    ```bash
    curl -X POST http://localhost:8000/v1/skills \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "release-notes-style",
        "description": "House style for release notes",
        "content": "# Release notes style\n\nLead with user-visible behaviour..."
      }'
    ```

    Import one from GitHub by passing `github_url` instead of `content`, upload a
    directory with `POST /v1/skills/upload`, or install one from the catalog with
    `POST /v1/skills/{skill_id}/install`. All four produce the same object; only
    `source_type` differs.
  </Step>

  <Step title="Attach it to the agent">
    `skill_ids` replaces the attached set, so send the full list you want.

    ```bash
    curl -X PATCH http://localhost:8000/v1/agents/<agent-id> \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"skill_ids": ["<skill-id>", "<other-skill-id>"]}'
    ```
  </Step>

  <Step title="Compose skills, if useful">
    A skill can contain skills, through `POST /v1/skills/{skill_id}/members`. Attach
    the parent and the agent gets the set. `POST /v1/skills/{skill_id}/flatten`
    resolves a composed skill into its effective content, which is the fastest way
    to see what an agent will actually receive.
  </Step>
</Steps>

## Verify

Read back the agent and confirm the skill ids:

```bash
curl -s http://localhost:8000/v1/agents/<agent-id> \
  -H "Authorization: Bearer $TOKEN"
```

Then run a task whose description needs the skill and watch the event feed. Skill
activation appears as a tool call, and file materialisation happens before the
next model turn.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The agent never activates the skill">
    Activation is a model decision. If the skill's `description` does not make
    its trigger obvious, the model has nothing to match on — the description is
    what appears in the catalog, not the content.
  </Accordion>
  <Accordion title="The skill's files are missing in the sandbox">
    Files land in the task workspace at activation, not at attach time. A task
    that never activated the skill has no reason to have its files.
  </Accordion>
  <Accordion title="Context is exhausted despite progressive disclosure">
    Attaching many skills still costs their catalog entries. Consider the
    `dynamic` context strategy — see
    [context strategies](/concepts/agents/context-strategies) .
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Skills" icon="robot" href="/concepts/agents/skills">
    A skill is a folder of files an agent loads only when a task calls for it
  </Card>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Create an agent, bind it to a model instance, and give it instructions and
    tools
  </Card>
  <Card title="Registry and catalog" icon="plug" href="/concepts/integration/registry-and-catalog">
    Built-in agents, MCP servers, skills
  </Card>
</Columns>
