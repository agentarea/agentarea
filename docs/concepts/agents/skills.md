---
title: Skills
type: concept
summary: A skill is a folder of files an agent loads only when a task calls for it — this page covers the three tiers of disclosure, where the files land, and what the model is told at each stage.
prerequisites:
  - /concepts/agents/what-is-an-agent
related:
  - /concepts/agents/context-strategies
  - /concepts/sandbox/sessions
  - /concepts/execution/artifacts
  - /concepts/governance/tool-authorization
last_updated: 2026-07-29
---

# Skills

A skill is a folder of files with a `SKILL.md` manifest at its root, attached to
an agent, and loaded into the model's context only when a task appears to need
it. The point is that an agent can have twenty skills without paying for twenty
skills on every request: what the model sees up front is a one-line description
of each, and the full text arrives only after the model asks for it.

That staging is called progressive disclosure, and in AgentArea it has three
tiers rather than the usual two — because the third tier puts files on a disk,
not text in a prompt.

## The problem

Instructions do not compose. Everything an agent might need to know has to fit
in one system prompt, so a prompt that covers ten procedures is ten times too
long for the nine requests that need one of them. The cost is not only tokens:
a model given ten procedures at once follows the wrong one more often than a
model given the right one on its own.

The naive fix — retrieve relevant instructions per request — trades a length
problem for a retrieval problem, and adds an embedding index, a chunking policy
and a similarity threshold to a system that had none of those. It also puts a
ranker between the author and the model, so an author who writes a procedure
cannot predict when it will be used.

There is a second, less obvious problem. Procedures are rarely only prose. A
procedure that says "run the migration checker" needs the migration checker to
exist somewhere the agent can run it, and injecting a Python script into a
prompt does not put it on a disk.

## How AgentArea approaches it

The model decides, from a description it can read, whether to load a skill. No
ranker, no embeddings. The decision is a tool call, so it is visible in the
event stream and subject to the same policy gate as any other tool call.

### Tier 1 — the catalog

When the agent's config carries any skills, the workflow builds a `SkillEntry`
per skill and appends a catalog block to the agent instruction. The block lists
name and description only, under an `## Available Skills` heading that tells the
model to call `activate_skill` when a task matches one.

At the same time an `activate_skill` tool is injected into the tool list. Its
schema is not a free-form string: `get_schema` overrides the generated schema to
constrain `skill_name` to an enum of exactly the available names, so the model
cannot invent one.

The catalog is appended to the instruction, not stored on the agent, so it is
rebuilt on every run and reflects the skills attached at that moment.

Nothing is disclosed unconditionally. The assembled tool list, `activate_skill`
included, passes through `filter_disclosed_tools` against the task's effective
policy before the model sees it, and the workflow logs how many tools were
withheld. See [tool authorization](/concepts/governance/tool-authorization).

### Tier 2 — activation

`activate_skill` runs inside the workflow rather than as a Temporal activity —
the content is already in workflow state, so there is nothing to fetch. It is
still gated: `_gate_tool_call` runs first, and a denied call never reaches the
skill.

The tool returns the skill's `SKILL.md` text wrapped in a
`<skill_content name="...">` element, followed by a list of the skill's other
files. Activation is idempotent per run: calling it twice returns "already
active in this session" instead of a second copy of the text.

Activated skill content is then protected from context compaction. `SkillContextGuard`
identifies these messages two ways — by tool name `activate_skill`, and by the
`<skill_content` tag as a fallback — and the compaction boundary search skips
any boundary that would drop one. Compaction otherwise triggers at 75% of the
effective context window, which is itself the model's window less a 15% reserve
for output.

### Tier 3 — materialization

Immediately after activation the workflow copies the skill's whole folder into
the task's sandbox workspace, under `skills/<slug>-<hash8>/`. From that point
the agent reaches the skill's scripts with an ordinary shell command. There is
no separate "run skill script" tool, and that absence is the design: one
execution path, not two.

Three details of the layout are deliberate.

The directory is keyed on a hash of the skill id, with the slug kept only for
readability. Slugging the display name collapses distinct skills — "deploy_api"
and "Deploy API" both reduce to `deploy-api` — and two skills sharing a
directory means the agent reads one skill's manifest and runs the other's
scripts.

A skill that is only prose is still a folder. `assemble_skill_bundle` writes the
stored text as `SKILL.md` when no manifest is present among the files, so there
is one kind of skill rather than a "content-only" second kind needing its own
handling.

An unsafe path rejects the entire bundle. A path that is absolute, or contains
`..`, raises rather than being skipped, because silently dropping one file can
turn a valid skill into a subtly broken one and it violates the workspace's
atomic commit contract.

Materialization failure is not fatal. The skill's instructions still stand on
their own, so the agent continues with a degraded skill rather than a dead task.

### Where a skill lives at rest

A skill row is workspace-scoped with a workspace-unique `slug`, and stores its
content one of two ways. Single-file skills keep their markdown in the `content`
column ("content mode"). Multi-file skills keep an `s3_path` to the stored
package ("package mode") and are read back file by file at materialization time.
`source_type` records where it came from: `content`, `zip`, `github`, or `path`.

Skills are managed through the `agentarea/skills` toolset as well as REST, and
the two are kept in parity by a contract test. That toolset lives in the agents
library rather than in the API app specifically so that agents running in the
worker can register it — see Limits.

## Why not retrieval-augmented instructions

The obvious alternative is to embed every skill, retrieve the top-k for each
request, and inject them. AgentArea does not, and the reasons are worth being
concrete about.

A retriever adds infrastructure that has to be right: an embedding model, a
chunk size, a similarity threshold, and a re-index step every time a skill is
edited. Each is a tuning surface that fails quietly — a threshold slightly too
high silently stops loading a skill, and nothing in the transcript says so.

The model already has the judgement being outsourced. It has read the task and
the descriptions; asking it to pick is one tool call against a closed enum,
which is a decision it makes well and, more importantly, a decision that appears
in the event stream. A retrieval hit does not appear anywhere, so "why did it
not use the deployment skill" has no answer.

And retrieval only solves the prose half. Files still have to reach a disk, and
once you have built the copy-into-the-workspace path for that, the model asking
for a folder by name is a smaller mechanism than the model asking for chunks by
similarity.

The cost is real and should be stated. Selection quality depends entirely on how
well descriptions are written, since the description is the only signal the model
has. A skill with a vague description will not be picked, and there is no
relevance score to inspect afterwards — only the presence or absence of an
`activate_skill` call.

## Limits

- **The catalog does not name a skill's files.** For a package-mode skill, the
  file list built into the config is the literal placeholder
  `["(additional files available)"]`, not the real filenames. The model learns
  the actual names only after activation materializes the folder.
- **An early activation can block compaction entirely.** The boundary search
  rejects any split that would drop protected skill content, and returns 0 — no
  compaction — when no safe boundary exists. A skill activated in the first
  iterations pins everything after it.
- **The activation registry is keyed by skill name.** `build_registry` maps name
  to entry, so two attached skills with the same name collapse to one. The
  workspace uniqueness constraint is on `slug`, not on `name`.
- **Content-mode skills cannot be promoted to packages in place.** `edit_content`
  rejects a multi-file payload for a content-mode skill and directs you to
  delete and recreate; no silent promotion happens.
- **Authoring limits are enforced at the toolset, not the model.** Inline
  creation caps at 200 files, 5 MB total, and path depth 10. GitHub import caps
  at a 25 MB repository archive, 200 files and 10 MB per package, 50 `SKILL.md`
  candidates, and 10 packages per import.
- **Skills are not advertised on the agent card.** The card lists three generic
  capabilities — `text-processing`, and conditionally `tool-execution` and
  `task-planning` — and never enumerates attached skills. A remote A2A caller
  cannot discover them.
- **A failed toolset import is silent.** The code tools loader imports every
  platform toolset module inside a try/except that logs at debug level, so a
  toolset that fails to import is absent from the registry with no error
  surfaced to the operator or the agent. This is why `agentarea/skills` was moved
  out of the API app into the agents library. The related claim that
  worker-run agents cannot reach `agentarea_api.tools.*` at all does not hold as
  stated: the worker declares `agentarea-api` as a dependency and those modules
  import cleanly in the workspace install. The residual risk is the silent skip,
  not a guaranteed absence.

## Related

- [What is an agent](/concepts/agents/what-is-an-agent) — how skills attach, and
  the configuration/policy line.
- [Context strategies](/concepts/agents/context-strategies) — the other half of
  what the model sees, and what gets offloaded.
- [Sandbox sessions](/concepts/sandbox/sessions) — the workspace a skill's files
  are copied into.
- [Tool authorization](/concepts/governance/tool-authorization) — the gate
  `activate_skill` clears like any other tool.
