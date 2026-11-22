---
title: Deploy agents from a folder
type: guide
description: "Describe a team of agents, their MCP servers, skills, policies and schedules as files, and deploy them into a workspace with the CLI."
prerequisites:
  - /concepts/integration/bundles
related:
  - /guides/agents/create-and-configure
  - /guides/agents/attach-skills
  - /guides/triggers/schedule-an-agent
  - /guides/governance/set-a-budget
last_updated: 2026-11-22
---

A bundle folder is a directory with `agentarea.yaml` at its root. That file
names the [bundle](/concepts/integration/bundles) and says which files belong
to it: any number of agents, plus the MCP servers, skills, policies, schedules
and channels they use. `agentarea deploy` installs the folder into one
workspace, and the next deploy updates that same install. Use a folder when the
agents are a project you keep in version control; use the raw bundle document
when you install something someone else published.

## Prerequisites

<Info>
- A running platform and a workspace — see [Run AgentArea locally](/quickstart).
- The `agentarea` CLI, signed in: `agentarea login --api-url=<api>`.
- An active chat model instance in the workspace, which the agents run on.
</Info>

## The entry file

`agentarea.yaml` is the only file with a fixed name and place. Where the other
files live is up to you: each section lists them by glob.

```yaml
# agentarea.yaml
name: acme-content
schema_version: 1
setup:
  model: {label: Model instance, required: true}
  bot_token: {label: Telegram bot token, type: secret, required: true}
defaults:
  model: ${setup.model}
agents: {include: ./agents/*.md, exclude: ./agents/drafts/*}
mcp: {include: ./mcp/*.yaml}
skills: {include: ./skills/*/}
policies: {include: ./policies/*.yaml}
schedules: {include: ./schedules/*.md}
channels: {include: ./channels/*.yaml}
targets:
  dev: {workspace: acme-dev}
  prod: {workspace: acme, setup: {model: claude-sonnet-5-5}}
```

| Key | Holds | Required |
|---|---|---|
| `name` | The bundle's name in the workspace | Yes |
| `schema_version` | `1`; any other value is refused | Yes |
| `display_name`, `description` | Shown for the bundle | No |
| `setup` | Values asked at deploy, keyed by setup key: `label` (required), `type` (`string`, `secret`, `number`, `boolean`, `select`), `required`, `help`, `default`, `options`, `min`, `max` | No |
| `defaults` | `model`, `reasoning_effort`, `reasoning_max_tokens` and `limits` for every agent that does not set its own | No |
| `targets` | Named workspaces to deploy to, each with its own `setup` values | No |
| `agents`, `mcp`, `skills`, `policies`, `schedules`, `channels` | One section per kind of object | At least one |

Each section is a mapping:

- `include` and `exclude` take a glob or a list of globs, relative to the
  folder: `*` and `?` match within one path segment, `**` across segments.
- Any other key is an object written inline under that key, so a whole bundle
  can live in `agentarea.yaml`. An inline agent takes its prompt as
  `instruction`, an inline schedule as `prompt`.

A file that no `include` selects is not deployed; the plan lists it as
`ignored`. A file two sections select is an error. There is no default glob: an
`agentarea.yaml` without includes or inline objects fails.

Agents and schedules are Markdown files with YAML front matter. MCP servers,
policies and channels are YAML files (`.yaml` or `.yml`). A skill is a
directory holding `SKILL.md`; its glob may name the directory or the
`SKILL.md`.

An object's key is the `name` written inside it, not its file name. It matches
`[a-zA-Z][a-zA-Z0-9_-]*`, two objects of the same kind may not share it, and a
file whose name differs from its `name` gets a warning. Moving a file does not
change the object; changing its `name` does — see
[rename an object](#rename-an-object).

## Steps

<Steps titleSize="h3">
  <Step title="Scaffold the folder">
    ```bash
    agentarea init acme-content
    cd acme-content
    ```

    This writes `agentarea.yaml` with one `model` setup field and an `agents`
    include, and `agents/acme-content.md`. It refuses to overwrite either file,
    or a folder that has an `agent.yaml`.
  </Step>

  <Step title="Write the agents">
    One Markdown file per agent. The front matter is its configuration; the
    body is its system prompt.

    ```markdown
    ---
    name: writer
    description: Writes posts from the editor's brief
    model: ${setup.model}
    skills: [brand-voice]
    mcp: [sheets]
    delegates: [publisher]
    limits: {run_usd: 2}
    builtin_tools: {ask_human_form: false}
    ---
    You write posts for Acme from the brief the editor gives you.
    ```

    | Field | Meaning |
    |---|---|
    | `name` | The agent's key. Required |
    | `display_name`, `description` | Shown in the workspace; `display_name` defaults to `name` |
    | `model` | A model instance id, an instance name, or a model name that exactly one active chat instance of the workspace has. A literal or `${setup.<key>}` |
    | `reasoning_effort` or `reasoning_max_tokens` | A reasoning level the model lists, or a token budget. Not both |
    | `client` | The id of a Codex or Claude Code client whose runner runs the agent's tasks |
    | `toolsets` | Built-in toolsets, such as `agentarea/shell` |
    | `skills`, `mcp` | Keys of skills and MCP servers of this bundle the agent uses |
    | `delegates` | Keys of agents of this bundle this agent may hand work to |
    | `limits` | `monthly_<cur>` and `run_<cur>`: the agent's monthly spend cap and the budget of one run |
    | `builtin_tools` | `ask_human_form: false` switches off the built-in form tool |

    Skills, MCP servers and delegates are listed on each agent and never
    inherited: `defaults` refuses `skills`, `mcp`, `delegates` and `toolsets`,
    so every grant of access is a line in that agent's file. A delegate that
    is not an agent of the bundle, or agents that delegate in a cycle, fail
    the plan.

    A model name that matches no instance, or several, blocks the plan and
    lists the candidates. `<cur>` in a limit is the deployment's billing
    currency in lower case; another currency blocks the plan. An agent's own
    `limits` key overrides the one from `defaults`, and `null` drops it.
  </Step>

  <Step title="Add MCP servers">
    One YAML file per server. Name a server from the catalog by its id and
    give it the credentials it asks for:

    ```yaml
    # mcp/sheets.yaml
    name: sheets
    display_name: Google Sheets
    catalog: io.github.owner/sheets
    bindings:
      Authorization: "${secret.sheets-token}"
    ```

    A server that is not in the catalog takes `json_spec` instead of
    `catalog`; set exactly one. A `bindings` key is a header for a remote
    server and an environment variable otherwise. Its value is one of:

    | Value | What the server gets |
    |---|---|
    | `${secret.<name>}` | A reference to the workspace secret `<name>`, read each time the server starts. Must be the whole value; you must be the secret's creator or a workspace admin |
    | `${setup.<key>}`, alone or inside a string | The deploy's value, copied into the server's own secret |

    A `command`-type server runs only with `npx`, `uvx`, `uv`, `python`,
    `python3`, `node`, `bunx` or `deno`; any other command shows as
    `unsupported` in the plan and its agents deploy without it.
  </Step>

  <Step title="Add skills">
    ```markdown
    <!-- skills/brand-voice/SKILL.md -->
    ---
    name: brand-voice
    ---
    Write in Acme's voice: short sentences, no exclamation marks.
    ```

    Every text file in the skill's directory installs with it as one skill
    package. A skill directory inside another skill directory is an error.
  </Step>

  <Step title="Add policies">
    A policy in a bundle only tightens, and only for the bundle's own agents.

    ```yaml
    # policies/publish-approval.yaml
    name: publish-approval
    subject: [writer, publisher]
    target: "tool:publish_post"
    effect: approval
    ```

    `subject` is required: an agent key, a list of agent keys, or `"*"` for
    every agent of the bundle. A single agent, or a list of one, keeps the
    policy's `name` as its key. A list of several or `"*"` becomes one policy
    per agent, keyed `<name>-<agent>`. `subject: workspace` and `effect: allow` are
    refused — rules for the whole workspace, or rules that loosen, belong to
    an admin through the policy API. The other fields are `params`,
    `condition`, `priority`, `enabled` and `message`.

    An agent's `limits` and `builtin_tools` install policies too, keyed
    `<agent>-monthly-cap`, `<agent>-run-cap` and `<agent>-no-ask-human-form`.
  </Step>

  <Step title="Add schedules and channels">
    Both name the agent they run with `agent`, the agent's key.

    ```markdown
    <!-- schedules/mwf-posts.md -->
    ---
    name: mwf-posts
    agent: writer
    cron: "0 9 * * 1,3,5"
    timezone: Europe/Berlin
    enabled: true
    ---
    Write today's post from the latest brief.
    ```

    ```yaml
    # channels/inbox.yaml
    name: inbox
    type: telegram
    agent: lead
    bindings:
      bot_token: "${setup.bot_token}"
    enabled: true
    ```

    A schedule's body is the prompt the agent is given. Leave `enabled` out
    and the schedule or channel installs disabled — see
    [schedule an agent](/guides/triggers/schedule-an-agent).
  </Step>

  <Step title="Preview the plan">
    ```bash
    agentarea deploy . --dry-run
    ```

    The CLI sends every text file of the folder except dotfiles, dot
    directories (`.agentarea/`, `.git/`) and `node_modules`, capped at 5MB,
    and prints the plan without writing anything:

    ```text
    Creates bundle acme-content
    Agents:
      agent      skills       mcp     delegates
      lead       none         none    writer
      writer     brand-voice  sheets  publisher
      publisher  none         none    none
    Create:
      agent       lead
      agent       writer
      agent       publisher
      mcp         sheets
      skill       brand-voice
      channel     inbox
      policy      publish-approval-writer
      policy      publish-approval-publisher
      policy      writer-run-cap
      policy      writer-no-ask-human-form
      automation  mwf-posts
    ```

    The first line says whether the deploy creates the bundle or updates one,
    and for an update who deployed it last and from which git commit. The
    table shows what each agent can reach. Every object is then tagged
    `create`, `update`, `unchanged`, `orphaned`, `changes not applied`,
    `already exists` or `unsupported`, followed by issues. A blocking issue
    stops the deploy; a warning does not.

    For CI, `agentarea deploy . --plan-json` prints the plan as JSON and
    exits 1 on a blocking issue, 0 otherwise, without asking anything. A policy
    check such as Conftest can read it.
  </Step>

  <Step title="Deploy">
    ```bash
    agentarea deploy . --set model=claude-sonnet-5-5 --set bot_token=123:abc --workspace acme
    ```

    `--set key=value` gives one setup value; repeat it per field. A terminal
    asks for a required value that is missing; elsewhere the deploy stops.
    Without `--yes` the CLI shows the plan and asks before it installs.
    `--workspace` can be saved once with `agentarea workspace use acme`.

    The install carries out exactly the plan you confirmed. If someone
    deployed the bundle in between, it refuses with `Someone deployed this
    bundle after the plan was made; run deploy again to see the new plan.` and
    writes nothing.
  </Step>
</Steps>

## Deploy to several workspaces

Each environment is its own workspace. Name them under `targets:` and pick one
with `--target`:

```bash
agentarea deploy . --target prod --yes
```

The deploy runs in the target's `workspace` with its `setup` values; a
`--set` for the same key still wins. An unknown target, `--target` without a
`targets:` section, or a `--workspace` that names another workspace is an
error. Secrets and connections are resolved in the target workspace, never
copied between them.

## Which bundle a deploy updates

After a deploy the CLI records the install in `.agentarea/deployments.json`,
one entry per API URL and workspace:

```json
{
  "version": 1,
  "deployments": [
    {
      "api_url": "https://api.agentarea.ai",
      "workspace": "acme",
      "install_id": "6f1c2a9e-1d0b-4b8e-9c55-2f3b8d7e4a10",
      "name": "acme-content",
      "deployed_at": "2026-11-22T10:00:00.000Z"
    }
  ]
}
```

The next deploy to that API and workspace updates the install by this id, so
changing `name` in `agentarea.yaml` renames the bundle instead of creating a
second one. The file holds no secrets. Commit it if your team and CI should
deploy into the same bundle; without it, name the bundle explicitly:

| Source | Wins over |
|---|---|
| `--into <bundle>` (install id or name) | everything below |
| `AGENTAREA_BUNDLE_ID` | the file |
| the entry in `.agentarea/deployments.json` | — |

With none of them, the deploy creates the bundle when its name is free. When a
bundle of that name already exists, it never deploys into it silently: a
terminal asks, naming who deployed it last and when, and a non-interactive run
stops until you pass `--into <name>`.

<Warning>
A copied folder that keeps `.agentarea/` updates the original bundle. The
plan's first line names the bundle it updates; read it before you confirm.
</Warning>

## What a redeploy changes

- An object this bundle created is updated in place when its file or a
  `--set` value it uses changed, and left alone otherwise.
- An MCP server this bundle created is updated in place: its spec, its
  environment and its headers. A secret binding you do not pass again keeps
  the value already stored. Every redeploy re-discovers each server's tools;
  the result shows `tools re-discovered: <n>`, or why discovery failed.
- An MCP server cannot switch between `catalog` and `json_spec`, change its
  catalog id, or change transport (for example from `docker` to `url`) on
  redeploy. The plan blocks with `give it a new key`: change the server's
  `name`, without `renamed_from`, and the deploy creates a new server.
- **Removing a file does not delete what it created.** The object shows as
  `orphaned` and keeps running; removing it is a manual step.
- Nothing is matched by name. An agent or server that only carries the same
  name, made by hand, is not this bundle's, and the deploy creates its own.
- A redeploy does not ask for a secret again. Pass a `--set` only for a value
  an object needs for the first time or one you are replacing.
- A deploy that fails partway removes what it created before the failure;
  running the same command again finishes the job.

## Rename an object

An object is identified by its key, so a changed `name` alone deploys a new
object and leaves the old one `orphaned`. To keep the object, set
`renamed_from` to its old key in the same file:

```markdown
---
name: copywriter
renamed_from: writer
---
You write posts for Acme from the brief the editor gives you.
```

Every kind takes `renamed_from`: agents, MCP servers, skills (in `SKILL.md`),
policies, schedules and channels. The plan shows the object as an update with
`renamed writer → copywriter`, and whatever referred to the old key — another
agent's `delegates`, a schedule's `agent`, a policy's `subject` — follows the
new one. A `renamed_from` that the last install does not have is a warning, and
the object is created new. Two objects claiming one old key, or an old key the
bundle still declares, block the plan. Once the rename is deployed,
`renamed_from` can be removed.

## Moving from agent.yaml

A folder with `agent.yaml` and `instructions.md` instead of `agentarea.yaml`
still deploys as one agent, with a deprecation warning. A folder with both
files is refused. To move a deployed one-agent folder without creating a
second agent:

1. Write `agentarea.yaml` with the same `name` and one include per
   subdirectory you keep (`mcp`, `skills`, `schedules`, `channels`,
   `policies`).
2. Move the fields of `agent.yaml` into the front matter of
   `agents/<name>.md`, and `instructions.md` into its body.
3. Add `renamed_from: agent` to that front matter. The old layout's agent had
   the key `agent`; without `renamed_from` the plan blocks, since the deploy
   would create a second agent and leave the first `orphaned`.
4. In the old layout an object's key was its file or directory name, and `name`
   was the name shown. Set `name` to the old key and move the shown name to
   `display_name`, or the object is deployed as new.
5. Give every schedule and channel `agent: <name>` and every policy
   `subject: <name>`; nothing binds to the one agent by default any more.
6. Run `agentarea deploy . --dry-run`. The folder has no
   `.agentarea/deployments.json` yet, so a terminal asks whether to deploy
   into the existing bundle of that name; in CI pass `--into <name>`. Check
   that the plan updates, rather than creates, what the old folder installed.

## Verify

```bash
agentarea agents list --workspace acme
```

lists the bundle's agents. To confirm one runs, submit a task against its id —
see [start a task](/guides/tasks/start-a-task).

## Troubleshooting

<AccordionGroup>
  <Accordion title="Deploy fails with No agentarea.yaml">
    The folder root has neither `agentarea.yaml` nor `agent.yaml`. Run
    `agentarea init <dir>`, or deploy the folder that holds the entry file.
  </Accordion>
  <Accordion title="A file was not deployed">
    No `include` selects it, and the plan lists it as `ignored`. Widen the
    section's glob, or check that an `exclude` does not match it.
  </Accordion>
  <Accordion title="Deploy stops: the bundle already exists">
    Another install has this bundle's name and the folder does not say to
    deploy into it. Pass `--into <name>` if it is yours; otherwise change
    `name` in `agentarea.yaml`.
  </Accordion>
  <Accordion title="The bundle this folder deploys into no longer exists">
    The install in `.agentarea/deployments.json` was deleted. A terminal offers
    to create it again; in CI, remove the entry or pass `--into <bundle>`.
  </Accordion>
  <Accordion title="The plan blocks on an agent's model">
    The name matches no active chat model instance, or several. Use the
    instance's id, or a name only one instance has.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Bundles" icon="plug" href="/concepts/integration/bundles">
    The document a folder loads into, and why it is portable by key
  </Card>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Build an agent over the API instead of from files
  </Card>
  <Card title="Schedule an agent" icon="plug" href="/guides/triggers/schedule-an-agent">
    Turning on the schedules a folder installs disabled
  </Card>
  <Card title="Set a budget" icon="scale-balanced" href="/guides/governance/set-a-budget">
    The caps an agent's limits and a cap policy install
  </Card>
</Columns>
