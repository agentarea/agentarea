---
title: Context strategies
type: concept
summary: Three settings — static, hybrid and dynamic — decide whether large tool outputs are offloaded to object storage, whether compacted history is preserved, and whether tools are disclosed lazily.
prerequisites:
  - /concepts/agents/what-is-an-agent
  - /concepts/execution/tasks
related:
  - /concepts/agents/skills
  - /concepts/execution/durable-execution
  - /concepts/execution/artifacts
  - /concepts/integration/mcp
last_updated: 2026-07-29
---

# Context strategies

A long agent run fills its context window with material it will never read
again: a 40,000-character command output, twelve tool schemas it never called,
thirty turns of a conversation whose conclusion is one sentence. A context
strategy decides what the runtime does about that — what gets moved out of the
prompt and left retrievable, and what gets withheld until asked for.

There are three values: `static`, `hybrid` and `dynamic`. `hybrid` is the
default, and each one is a superset of the last.

## The problem

Context windows are large, but they are not the binding constraint people
expect. Three separate pressures push against them, and they want different
answers.

The first is a single enormous tool result. One `find` over a big tree can spend
a third of a window on output the agent needed two lines of. Truncating loses
the two lines as often as not.

The second is accumulated history. Compaction — summarizing old turns to reclaim
room — is the standard answer, and it is lossy by construction. Once a turn has
been summarized, a question that depends on its detail has nowhere to go.

The third is tool schemas. An agent with eight MCP servers attached carries
every tool definition from all eight on every request, whether or not this task
touches any of them, and schemas are not small.

Solving all three unconditionally is the wrong call, because each solution costs
something. Offloading adds a round trip and a read-back tool the model has to
understand. Lazy tool disclosure adds an activation turn before the first real
tool call, and a model that handles it badly stalls. So the platform makes it a
setting rather than a default behaviour.

## How AgentArea approaches it

### What each strategy turns on

| | `static` | `hybrid` (default) | `dynamic` |
|---|---|---|---|
| Offload large tool outputs | no | yes | yes |
| Preserve history before compaction | no | yes | yes |
| Disclose tools lazily | no | no | yes |

Note what is *not* in the table: compaction itself. Compaction runs under all
three strategies. What `static` gives up is the preservation of what compaction
discards, not the discarding.

### Resolution

The strategy is resolved once, early in the run, before tool discovery — it has
to be, because it decides which discovery activity runs. Resolution order is the
agent's override, then the model spec's `default_context_strategy`, then
`"hybrid"`. The resolved value is stored on workflow state and carried across
continue-as-new so a long run does not change strategy mid-flight.

An unrecognized value does not raise. It resolves to `hybrid`. See Limits — this
matters more than it sounds.

### Output offloading

Under `hybrid` and `dynamic`, a tool result longer than 8,000 characters (about
2,000 tokens) is written to object storage under `tasks/{workspace_id}/{task_id}`
and replaced in the conversation by a summary.

The summary is not a truncation. It carries a header naming the stored id with
the exact character and line counts, then the first 500 characters, then — if
the content is longer than head plus tail — the last 200 characters, and it ends
by telling the model how to get the rest:

```
[Output stored as <output_id> — 41,208 chars, 913 lines]
Preview:
<first 500 chars>
...
<last 200 chars>

Use read_tool_output("<output_id>") for full content,
or read_tool_output("<output_id>", grep="pattern") to search.
```

The `grep` parameter is the point. The common case is not "read all 41,000
characters back" but "find the three lines that matter", and offloading turns an
unaffordable read into an affordable search. A read-back is itself capped at
16,000 characters.

Offloading is best-effort in both directions. If the store fails inside the
workflow, the full content stays in the conversation — the agent is never
blocked by a storage outage. The same offload applied inside an activity, where
the payload would otherwise become Temporal history, degrades differently: it
truncates at 8,000 characters and says so explicitly in the text.

### History preservation

Under `hybrid` and `dynamic`, the messages about to be compacted are written to
object storage as a numbered chunk first, and a counter increments. Compaction
then proceeds as usual.

This makes `recall_history` meaningfully better. When the model calls it with a
`grep` or `tool_name` filter and at least one chunk has been stored, the
workflow searches the preserved chunks in object storage and returns up to 20
matches. Only if that search finds nothing or fails does it fall back to
querying the database event log.

Under `static` there are no chunks, so `recall_history` has only the event-log
fallback.

Preservation is also best-effort — a failed store logs a warning and compaction
continues, because refusing to compact would leave the run wedged against its
context limit.

### When compaction happens

Usage is tracked against an effective limit of the model's context window less a
15% reserve for output. A warning fires at 60% of that limit; compaction
triggers at 75%.

Compaction cannot cut anywhere. `find_compaction_boundary` searches from the
largest possible split downwards for one that keeps the last 4 messages, does
not orphan a tool result whose originating tool call would be removed, and does
not drop [activated skill content](/concepts/agents/skills). If no such boundary
exists it returns 0 and compaction is skipped with a warning.

### Lazy tool disclosure

Only `dynamic` changes what tools the model is shown. Instead of discovering and
injecting every tool definition, the workflow discovers tool *providers* — MCP
servers, code toolsets, agents, built-ins — and injects a catalog block:

```
## Available Tool Sources
Use activate_tool_source("name") to enable tools before using them.

- **github** [mcp] (5 tools): list_repos, create_issue, search_code, ...
- **analyst** [agent] (3 tools): analyze_data, summarize, recommend
- **math** [code] (2 tools): calculate, convert_units
```

Each entry names the provider, its type, its tool count and up to five tool
names as a preview. Built-in providers are loaded eagerly regardless — they are
small and always relevant. An `activate_tool_source` tool is added whose
`source_name` enum contains exactly the not-yet-activated sources, so the model
cannot request one that does not exist. Activated sources are recorded on
workflow state and replayed across continue-as-new, so a long run does not have
to re-activate.

A separate, finer mechanism exists for OpenAPI connections and is not governed
by the context strategy at all: a tool config with `load_mode: "searchable"`
keeps its operation schemas out of the prompt behind a `load_tools` meta-tool
that reveals them by exact name. That is per-tool configuration, not a
strategy-wide switch.

## Why not always use dynamic

Dynamic looks strictly better — it is the superset — and it is not the default,
for two reasons.

It costs a turn. Under `dynamic` the model cannot call a tool until it has first
called `activate_tool_source`, which means at minimum one extra LLM round trip
before any work begins, and more when the model activates sources one at a time.
For a task that was always going to use the one MCP server the agent has, that
is pure overhead.

And it depends on a model behaviour that is not uniform. Choosing a source from
a catalog, activating it, and then calling a tool from it is a three-step plan
held across turns. Weaker models activate the wrong source, forget to activate
at all and hallucinate a tool call, or activate everything immediately — which
reproduces `static` while having paid for the extra turns. The eager path has no
such failure mode: the tool is either in the list or it is not.

`hybrid` is the default because its two features have no behavioural cost. The
model is not asked to do anything differently; large outputs arrive summarized
with a documented way to read more. The one thing it does ask is that
the model understands `read_tool_output`, and that is a normal tool call rather
than a multi-turn plan.

The cost of making this a setting at all is that the same agent behaves
differently on two models, and a bug that only appears under `dynamic` will not
reproduce on a model whose spec leaves the default unset.

## Limits

- **The per-agent override is not wired.** Resolution reads
  `agent_config["context_strategy"]` first, but the agent config the activity
  builds has no such field — `AgentConfigResult` carries only
  `default_context_strategy`. There is no `context_strategy` column on the agent
  and no API field for it. The agent-level override is always absent, so the
  model spec is the only thing that selects a strategy.
- **There is no auto-inference from the model name.** The model-spec DTO
  comments `default_context_strategy` as "Auto-inferred from model_name if
  None", and no inference exists. A null value resolves to `hybrid`.
- **An invalid value fails silently to `hybrid`.** Resolution catches the
  `ValueError` and returns `hybrid` with no log line, and the enum values are
  lowercase — so `"STATIC"` or `"Dynamic"` does not select what it looks like it
  selects, it selects `hybrid`.
- **Offloading is measured in characters, not tokens.** The 8,000-character
  threshold is documented as roughly 2,000 tokens, which holds for English prose
  and not for dense JSON, minified code, or non-Latin scripts.
- **The preview may not contain the useful part.** 500 characters of head and
  200 of tail is a small window on a 40,000-character output. The model has to
  decide from that whether a `read_tool_output` call is warranted.
- **Activating an unknown tool source is silent.** `ToolCatalog.activate`
  returns an empty list for a name it does not know rather than an error,
  deliberately, on the assumption the model hallucinated it.
- **Offload and preservation failures are invisible to the agent.** Both log a
  warning and continue. Under `hybrid`, a storage outage means history is
  compacted without being preserved, and `recall_history` silently has less to
  find.
- **`static` still compacts.** Choosing `static` does not preserve the full
  conversation; it only means nothing is written to object storage before
  compaction discards it.

## Related

- [Skills](/concepts/agents/skills) — activated skill content is exempt from
  compaction, which interacts directly with the boundary search.
- [What is an agent](/concepts/agents/what-is-an-agent) — where model selection
  lives, and therefore where the strategy is chosen today.
- [Durable execution](/concepts/execution/durable-execution) — continue-as-new,
  which the resolved strategy and activated sources are carried across.
- [Artifacts](/concepts/execution/artifacts) — the other thing a task writes to
  object storage, on a different path and with different durability rules.
