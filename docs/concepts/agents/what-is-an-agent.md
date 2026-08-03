---
title: What is an agent
type: concept
summary: An agent is a workspace-scoped definition — an instruction, a model, a tool list and attached skills — and this page separates what it configures from what governs it.
prerequisites:
  - /agentic-networks
related:
  - /concepts/agents/skills
  - /concepts/agents/a2a
  - /concepts/agents/context-strategies
  - /concepts/execution/tasks
  - /concepts/governance/tool-authorization
last_updated: 2026-07-29
---

# What is an agent

An agent is a named, workspace-scoped definition of how to answer a request: an
instruction, a model to run it on, a set of tools it may reach for, and a set of
skills it can pull in when a task calls for them. It is not a running process.
Nothing executes until a [task](/concepts/execution/tasks) addresses it, and the
same definition can be running many tasks at once.

The distinction that matters most is the one between what an agent *is
configured with* and what it *is permitted to do*. Those are two different
systems in AgentArea, deliberately, and confusing them is the most common way to
misread the platform.

## The problem

The obvious way to build an agent platform is to make the agent the unit of
everything: its prompt, its credentials, its permissions, its spend limit, all
one object. That collapses the moment two people share a workspace. The person
who writes the prompt is rarely the person who decides the agent may send email
or spend 200 USD a month, and an agent that carries its own permissions is an
agent that grants itself permissions — anyone who can edit the prompt can edit
the authority.

It also makes an agent unshareable. If the definition embeds workspace database
ids, model instance ids and MCP instance ids, it cannot be moved to another
workspace without a rewrite, so agents stop being artifacts that can be
published, forked or version-controlled.

## How AgentArea approaches it

An agent is a row in the `agents` table carrying the `WorkspaceScopedMixin`,
with a workspace-unique `slug` as its stable human-readable identifier. Every
repository and service that touches it requires a `UserContext`, so an agent is
never reachable outside the workspace that owns it.

### What the definition holds

| Field | What it does |
|---|---|
| `name`, `slug`, `description` | Identity. `slug` is unique per workspace and is what URLs and delegation resolve against. |
| `instruction` | The system prompt. At execution the runtime manifest is appended to it, so what the model sees is longer than what you wrote. |
| `model_id` | A model instance in the workspace. A task cannot be created for an agent without one. |
| `tools` | A JSON list of tool configs. This is composition — what the agent is equipped with. |
| `skills` | A many-to-many edge to `skills` through `agent_skills`. |
| `planning` | Advertised in the agent card as a `task-planning` skill. |
| `a2ui_enabled` | Enables the interactive UI action channel on tasks. |
| `agent_type` | `stateless` or `stateful`. Stored and returned; see Limits. |
| `events_config` | Stored and returned; see Limits. |
| `registry_item_id` | Provenance. Set when the agent was forked copy-on-write from a catalog item, null when created from scratch. |

`tools` is a discriminated union on `type`, not a free-form blob. Four variants
exist — `code`, `mcp`, `agent`, `openapi` — and each carries only the settings it
can actually use. An `a2a_url` is unrepresentable on a code tool, because it
lives on `AgentToolSettings` alone. Legacy rows that carried cross-type keys
still parse; the alien keys are dropped.

### Skills are where the folder model is real

An agent definition is not a directory, but the things it composes are. A skill
is a package of files with a `SKILL.md` manifest at its root, and that shape is
load-bearing at execution time: activating a skill copies its files into the
task's sandbox workspace under `skills/<slug>-<hash8>/`, where the agent reaches
its scripts with an ordinary shell rather than a separate execution path.

The directory name is keyed on a hash of the skill id, not on the display name,
because slugging the name collapses distinct skills together — "deploy_api" and
"Deploy API" both reduce to `deploy-api`, and two skills sharing a directory
means the agent reads one skill's manifest and runs the other's scripts. An
unsafe path anywhere in a bundle rejects the whole bundle rather than dropping
the offending file, because a silently partial skill is worse than a failed one.

[Skills](/concepts/agents/skills) covers how one gets discovered and loaded.

### Configuration versus policy

Composition is candidacy, not permission. The `tools` list says what the agent
is equipped with; the [policy engine](/concepts/governance/policy-engine) says
what it may use. These are separate stores, and AgentArea moved a field across
that line rather than leave it ambiguous.

The per-tool "requires approval" toggle in the agent editor used to live in the
agent's `tools` JSON, where nothing enforced it. It now becomes an agent-scoped
`PolicyRule(target="tool:<name>", effect=APPROVAL)`, which the resolver folds
into the snapshot the workflow gate reads. The flag is deliberately *not*
persisted on the tool config — `strip_confirmation_flags` removes it before
write and `apply_approval_targets` reconstitutes it from the rules on read, so
the UI round-trips without the value acquiring a second home that could drift
from the first.

Two consequences follow. Editing an agent's tools reconciles its approval rules
as a side effect, and that reconciliation is idempotent: unticking a tool
deletes the rule rather than disabling it. And the reconciliation lives in
`AgentService` in the agents library rather than in the API app, so every path
that creates an agent — the REST router, bundle install, workspace import,
catalog fork — goes through the same home.

One naming subtlety leaks through. Policy judges the name the model calls, so a
code toolset's namespace is collapsed (`agentarea/shell` becomes `shell`) while
an MCP tool keeps the raw name it advertises.

### The portable form is a bundle

An agent moves between workspaces as part of a
[bundle](/concepts/integration/bundles), the canonical package format. Inside
one, entities reference each other by `key` and never by database id, which is
what makes the package portable; the installer resolves keys to real ids at
install time. A bundle can carry agents, MCP servers, skills, channels,
scheduled automations and policy rules together.

User-supplied values enter through exactly one door. `SetupField` declares what
the installer must collect, and everything else references those values through
`${setup.<key>}` placeholders — so a bundle never inlines a token, and the same
mechanism covers an MCP server's credentials and a channel's bot token.

Notably, a bundle can install `BundlePolicy` entries whose `subject` is either
the literal `"workspace"` or an agent's key. This is the configuration/policy
line drawn again at the package boundary: the policy travels alongside the
agent, addressed the same portable way, but it is still a policy rule rather
than a field on the agent.

## Why not a directory on disk

The obvious alternative — and one AgentArea has designed but not shipped — is to
make an agent a folder: `agent.yaml`, `instructions.md`, a `workspace/`
template, a `sandbox.yaml` declaring the execution environment, `tools/`,
`skills/`. It is a good model, it is how the skill layer already works, and it
is what a git-versioned agent wants to be.

It is not what runs today. There is no `agent.yaml`, no `sandbox.yaml` and no
per-agent `workspace/` template anywhere in the platform. The unit is the
database row described above, and the portable artifact is the bundle. A page
that described the folder model as current would be describing a branch, not the
product.

What the row model buys in exchange is worth naming, because it is the reason
the migration has not been urgent. Workspace scoping is enforced by the same
mixin as every other entity, so an agent cannot leak across a tenancy boundary
through a file path. Approval rules can be reconciled transactionally with the
agent write. And the catalog can fork a built-in into a workspace
copy-on-write, recording `registry_item_id` as forward provenance, without
materializing files anywhere.

The cost is equally real: an agent is not a diffable artifact, there is no
review-before-merge story for a prompt change, and the execution environment
(image, resource limits, egress profile) cannot be declared per agent at all —
it is a property of the sandbox runtime, not of the agent.

## Limits

- **`agent_type` selects nothing.** It is validated, stored, returned by the API
  and carried into the execution config, but no workflow branches on it. A
  `stateful` agent and a `stateless` agent execute identically today.
- **`events_config` has no execution consumer.** It is stored on the row and
  round-trips through the API and the registry sync; nothing in the execution
  library reads it.
- **The execution environment is not per-agent.** Image, resource limits and
  egress profile are properties of the sandbox runtime and cannot be declared on
  an agent definition.
- **`instruction` is capped at 5,000 characters on the import path** and 20,000
  in a bundle. These two limits differ, and the import schema is the tighter one.
- **The agent card advertises three generic skills, not the agent's actual
  skills.** `text-processing` is always present, `tool-execution` appears when
  the agent has any tools, `task-planning` when `planning` is set. Attached
  skills are not enumerated there — see [A2A](/concepts/agents/a2a).
- **A bundle pins one schema version.** `schema_version` must equal `0.1.0`
  exactly; there is no forward or backward compatibility range.
- **Approval reconciliation is scoped to the tools you send.** Rules are
  reconciled to exactly the ticked targets in the submitted config, so a write
  that omits a tool removes its approval rule.

## Related

- [Skills](/concepts/agents/skills) — how a skill is discovered, loaded and run.
- [Agent-to-agent communication](/concepts/agents/a2a) — how one agent invokes
  another, and when that goes over A2A.
- [Context strategies](/concepts/agents/context-strategies) — what the agent's
  model sees, and what gets offloaded.
- [Tool authorization](/concepts/governance/tool-authorization) — the layers a
  tool call clears once the agent is composed.
- [Tasks](/concepts/execution/tasks) — the unit that actually runs.
