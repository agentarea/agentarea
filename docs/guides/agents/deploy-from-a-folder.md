---
title: Deploy an agent from a folder
type: guide
description: "Lay out an agent as plain files in a folder and deploy it with the CLI, instead of hand-writing the bundle document."
prerequisites:
  - /concepts/integration/bundles
related:
  - /guides/agents/create-and-configure
  - /guides/agents/attach-skills
  - /guides/triggers/schedule-an-agent
  - /guides/governance/set-a-budget
last_updated: 2026-11-09
---

An agent folder is a directory of plain files — `agent.yaml`, an instruction
file, and one subdirectory per thing the agent needs — that the CLI loads into
a [bundle](/concepts/integration/bundles) and installs. Use this when you are
building an agent as a project you check into version control and iterate on
locally. Reach for the raw bundle document instead when you are installing
something someone else already published, or scripting an install with no
local files at all.

## Prerequisites

<Info>
- A running platform and a workspace — see [Run AgentArea locally](/quickstart).
- The `agentarea` CLI, signed in: `agentarea login --api-url=<api>`.
- Nothing else. `agent.yaml` is the only required file.
</Info>

## The folder layout

| Path | Produces | Required |
|---|---|---|
| `agent.yaml` | name, display name, description, model, reasoning, harness client, toolsets, setup fields | Yes |
| `instructions.md` | the agent's instruction | No — empty instruction if omitted |
| `skills/<key>/` | a skill attached to the agent: `SKILL.md` and any files it ships | No |
| `mcp/<key>.yaml` | an MCP server attached to the agent: a catalog server or a spec | No |
| `schedules/<key>.md` | a cron automation that runs the agent | No |
| `channels/<key>.yaml` | a messaging channel bound to the agent | No |
| `policies/<key>.yaml` | a governance rule; subject defaults to the agent | No |

Anything else — a stray `README.md`, a file directly under `skills/` — is
skipped with a warning, not an error. The whole folder describes one agent;
there is no way to define more than one per folder.

An entity `<key>` — the file or directory stem under `mcp/`, `skills/`,
`schedules/`, `channels/`, or `policies/` — matches
`[a-zA-Z][a-zA-Z0-9_-]*`: a letter, then any mix of letters, digits, `_`, and
`-`. A setup field's `key` in `agent.yaml` is stricter,
`[a-zA-Z][a-zA-Z0-9_]*` with no dashes, since it is interpolated literally
into `${setup.<key>}`.

## Steps

<Steps titleSize="h3">
  <Step title="Scaffold the folder">
    ```bash
    agentarea init my-researcher
    cd my-researcher
    ```

    This lays down `agent.yaml` and `instructions.md`. Edit `agent.yaml`:

    ```yaml
    name: researcher
    display_name: Researcher
    description: Finds things out and cites sources
    model: ${setup.model_id}
    toolsets: [agentarea/shell]
    setup:
      - {key: model_id, label: Model instance id, type: string, required: true}
      - {key: github_token, label: GitHub personal access token, type: secret, required: true}
    ```

    and `instructions.md`:

    ```markdown
    You research a topic and report back with sources. Be thorough and cite
    every claim.
    ```

    `name` is the only required field. It also becomes the bundle's name — the
    key a redeploy matches against, so renaming it starts a new agent rather
    than updating this one. `model` takes a literal model instance id or, as
    above, a `${setup.<key>}` reference resolved from `--set` at deploy time.

    Three more settings are optional:

    ```yaml
    reasoning_effort: high
    client: ${setup.runner_client_id}
    ```

    `reasoning_effort` is a level the model takes, such as `low` or `high`;
    `reasoning_max_tokens` is a token budget instead. Set one or neither,
    never both. `client` runs the agent's tasks through the runner of a Codex
    or Claude Code client of the workspace, named by the client's id — a
    literal id or a `${setup.<key>}` reference. A client's name is not unique,
    so a name is refused; a client you may not use, or one that is no runner's,
    blocks the deploy.
  </Step>

  <Step title="Attach an MCP server">
    One file per server, under `mcp/`; the file's stem is the key other files
    reference it by. Name a server from the catalog by its id, and give it the
    credentials it asks for:

    ```yaml
    # mcp/kassa.yaml
    name: YooKassa
    catalog: ru.yookassa/mcp
    bindings:
      Authorization: "Bearer ${setup.kassa_token}"
    ```

    The id is the catalog entry's: `<server>` for a remote server,
    `<server>/command` or `<server>/docker` for one the platform runs. The
    server connects the way the catalog's connect flow connects it, so the
    folder carries no endpoint, command or image. A `bindings` key is a header
    for a remote server and an environment variable otherwise. An id the
    catalog does not have blocks the deploy.

    A server that is not in the catalog takes its spec instead:

    ```yaml
    # mcp/github.yaml
    name: GitHub
    json_spec:
      type: url
      endpoint_url: https://api.githubcopilot.com/mcp/
    bindings:
      Authorization: "Bearer ${setup.github_token}"
    ```

    Set exactly one of `catalog` or `json_spec`. Docker and URL servers are
    always supported. A `command`-type server is
    only supported when the command is `npx`, `uvx`, `uv`, `python`, `python3`,
    `node`, `bunx`, or `deno` — a local path or a
    `${CLAUDE_PLUGIN_ROOT}`-relative binary is not. An unsupported command does
    not fail the deploy; it shows as `unsupported` in the plan and the agent is
    created without that tool.
  </Step>

  <Step title="Attach a skill">
    ```markdown
    <!-- skills/cite-sources/SKILL.md -->
    ---
    name: Cite sources
    ---
    # Cite sources

    For every factual claim, attach the source URL it came from.
    ```

    Everything in the skill's directory installs with it — a script under
    `skills/cite-sources/scripts/`, a reference doc — as one skill package;
    the agent reads the files when it activates the skill. `SKILL.md` must sit
    at the top of the directory. Binary files are skipped, like everywhere
    else in the folder.
  </Step>

  <Step title="Add a schedule, a channel, or a policy">
    All three are optional, and all three bind to the one agent in this
    folder.

    ```markdown
    <!-- schedules/daily.md -->
    ---
    cron: "0 9 * * *"
    timezone: Europe/Berlin
    enabled: true
    ---
    Research today's top story in our industry and summarize it.
    ```

    ```yaml
    # channels/inbox.yaml
    type: telegram
    name: Inbox
    bindings:
      bot_token: "${setup.telegram_bot_token}"
    ```

    ```yaml
    # policies/no-email.yaml
    target: "tool:send_email"
    effect: deny
    ```

    Leave `enabled` out of a schedule or channel and it installs disabled —
    see [schedule an agent](/guides/triggers/schedule-an-agent) for activating
    it afterwards. A policy's `subject` defaults to this agent; set it to
    `workspace` to bind the rule to the whole workspace instead.
  </Step>

  <Step title="Preview the plan">
    ```bash
    agentarea deploy . --dry-run
    ```

    Reads the folder — skipping dotfiles, `node_modules`, `.git`, and binary
    files, capped at 5MB total — and prints the plan without writing anything.
    Every entity is tagged `create`, `update`, `unchanged`, `orphaned`,
    `changes not applied`, `already exists`, or `unsupported`, alongside any
    issue found (a reference to an MCP key that does not exist, a binding that
    points at an undeclared setup field, and the like). A blocking issue stops
    the deploy; a warning does not.
  </Step>

  <Step title="Supply setup values and deploy">
    ```bash
    agentarea deploy . \
      --set model_id=3fa6c1e2-... \
      --set github_token=ghp_... \
      --set telegram_bot_token=123:abc \
      --workspace acme
    ```

    `--set` supplies one `key=value` pair per setup field; repeat it for each
    one. A required field with no value and no `default` in `agent.yaml` blocks
    the install before anything is written. Without `--yes`, `deploy` shows the
    same plan as `--dry-run` and asks for confirmation before it writes; add
    `--yes` to skip the prompt in a script or CI job. `--workspace` can instead
    be set once with `agentarea workspace use acme`.

    The install carries out exactly the plan you confirmed. If anything
    changed it in between — a teammate's deploy, an entity deleted by hand —
    the install refuses with `the deploy plan changed since it was shown` and
    writes nothing; run `deploy` again to see the new plan.
  </Step>
</Steps>

## What a redeploy changes

Run `agentarea deploy` again against an edited folder and it reconciles the
workspace against the new content, matched by the bundle's name — not by
re-creating everything:

- An agent, skill, schedule, channel, or policy this folder created before is
  updated in place when its file changed or a `--set` value it references
  changed — `--set model_id=<new-id>` against an otherwise untouched
  `agent.yaml` still shows as an update — and left alone otherwise.
- A changed skill is stored as its next version, so the skill's history keeps
  the one before it.
- **MCP servers are never updated on redeploy.** Edit `mcp/github.yaml` and
  redeploy, and the existing server instance is unchanged; the plan keeps
  showing `changes not applied` on every redeploy until you change it by
  editing the MCP server directly, not through the folder.
- **Removing a file does not delete what it created.** Delete
  `schedules/daily.md` and redeploy, and the schedule it created keeps
  running — the plan shows it as `orphaned`, not deleted. There is no prune
  flag; removing an entity for real is a manual step today.
- Nothing is matched by name. An agent, MCP server, skill or schedule that
  only carries the same name — one a teammate made by hand, for instance — is
  not this folder's, and the deploy creates its own. Something an earlier
  install linked instead of creating shows as `already exists` and is never
  changed. A rule with the same subject, target and effect as a policy file
  is the one exception: the deploy reuses it rather than writing a second,
  and the plan says `already exists`.
- An agent this folder created and someone has since archived counts as
  gone: the deploy creates the agent again.
- A redeploy changes only the agent's tools and skills the folder declares or
  the last deploy attached. A tool, delegate or skill added to the agent in
  the workspace stays, a declared tool keeps the settings it was given there,
  and every approval on the agent's tools stays as it was. `reasoning_effort`,
  `reasoning_max_tokens` and `client` are set only when `agent.yaml` names
  them, or named them last time and no longer does, which clears them.
- A redeploy does not ask for a secret again. Repeat a `--set` only for a
  value an entity needs for the first time (it is being created) or one you
  are intentionally replacing. A channel's stored credentials — a bot token,
  for instance — are rewritten only when you pass a new value for them;
  leave `--set telegram_bot_token=...` out and the one already stored keeps
  working. A credential that names a workspace secret is never replaced by a
  value: passing one for it blocks the deploy, so change that secret instead.
- Updating an entity this folder owns needs edit permission on it. If a
  teammate changed its permissions, or someone else now owns it by hand, the
  deploy stops on that entity instead of silently skipping it.
- A deploy that fails partway through removes whatever it created before the
  failure. An update it already applied stays, and the next deploy plans it
  again, so re-running the same command finishes the job.

## Verify

```bash
agentarea agents list --workspace acme
```

confirms the agent exists under the `name` from `agent.yaml`. To confirm it
actually runs, submit a task against its id — see
[start a task](/guides/tasks/start-a-task).

## Troubleshooting

<AccordionGroup>
  <Accordion title="`agentarea deploy` fails with `agent.yaml: missing`">
    The folder root has no `agent.yaml`. Every agent folder needs one at the
    top level; it cannot live in a subdirectory.
  </Accordion>
  <Accordion title="A file in the folder was silently not installed">
    Check the plan's issues — an unrecognized path, a binary file, or anything
    outside the layout above comes back as a warning, not an error, and is
    left out of the bundle.
  </Accordion>
  <Accordion title="Install refuses with `missing required setup field`">
    A field in `agent.yaml`'s `setup` list has `required: true`, no `default`,
    and no matching `--set key=value` on the deploy command. Supply it, or give
    it a `default` in `agent.yaml` if a missing value is actually fine.
  </Accordion>
  <Accordion title="An MCP server shows `unsupported` in the plan">
    Its `json_spec.command` is not one of the runtimes the platform can run
    (`npx`, `uvx`, `uv`, `python`, `python3`, `node`, `bunx`, `deno`), or it
    references a local path. The agent still deploys, without that tool
    attached.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Bundles" icon="plug" href="/concepts/integration/bundles">
    The document an agent folder loads into, and why it is portable by key
  </Card>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Build the same agent directly over the API instead of from files
  </Card>
  <Card title="Schedule an agent" icon="plug" href="/guides/triggers/schedule-an-agent">
    Activating the cron automation a `schedules/` file installs disabled
  </Card>
  <Card title="Set a budget" icon="scale-balanced" href="/guides/governance/set-a-budget">
    The ceiling types available to a `policies/` file's `cap` effect
  </Card>
</Columns>
