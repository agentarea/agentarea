# Page types: frontmatter contract, templates, splitting

## Frontmatter contract

Every page in `docs/` carries this block. Modelled on Vercel's docs, which
attach `type`, `prerequisites`, `related` and `last_updated` to every page —
the fields are machine-checkable, which is why they stay accurate.

```yaml
---
title: Run a command in a sandbox
type: guide                    # tutorial | guide | concept | reference
summary: Execute a shell command inside a task's sandbox and read its output.
prerequisites:
  - /concepts/sandbox/sessions
related:
  - /guides/sandbox/collect-artifacts-and-logs
  - /reference/limits
last_updated: 2026-07-29
---
```

Rules:

- `type` is the genre. If you cannot pick one, the page is two pages.
- `summary` is one sentence, states what the reader gets, and is written for
  search results — not "This page describes...".
- `prerequisites` links pages the reader must have read. Empty list is allowed
  and meaningful; a missing field is not.
- `related` is for lateral moves, not prerequisites. Three to five entries.
- `last_updated` is a date, updated when the content changes, not when a typo is
  fixed.

---

## Tutorial

Learning-oriented. The reader has nothing working and finishes with something
that runs. The single hardest genre, because the temptation to explain is
constant and must be resisted.

```markdown
# <Verb> a <thing>

<One paragraph: what you will have built by the end. Show the end state first.>

## Before you start

<Prerequisites as a checklist. Versions pinned. Nothing optional.>

## Step 1 — <verb phrase>

<Exactly one action. Full command, full file contents, no ellipsis.>

<What the reader should now see. Real output, copied from a real run.>

## Step 2 — ...

## What you built

<Restate the end state. Link the next tutorial, and the concept page that
explains what just happened.>
```

Constraints:

- **No choices.** No "you can also", no "alternatively", no "depending on your
  setup". Every branch is a place a beginner gets lost. Branches belong in guides.
- **No explanation beyond one sentence at a time.** Link to the concept page.
- **Every command must be runnable as written.** Copy the real output in.
- **It must work end to end on a clean machine.** Verify before shipping.

## Guide (how-to)

Task-oriented. The reader knows what they want and is stuck on how.

```markdown
# <Verb> <object>

<One paragraph: when you would do this, and when you would not.>

## Prerequisites

<Bulleted, linked.>

## Steps

1. ...
2. ...

## Verify

<How to confirm it worked. Concrete: a command, a status, a log line.>

## Troubleshooting

<The two or three ways this actually fails, with the fix. Written from real
support threads, not imagination.>

## Related

<Links.>
```

Constraints:

- Title starts with a verb. "MCP servers" is not a guide title; "Add a hosted
  MCP server" is.
- Options are allowed here — that is the difference from a tutorial — but each
  option must say when to pick it.
- A guide with no `Verify` section is unfinished.

## Concept

Understanding-oriented. The reader wants the mental model and the reasoning.

```markdown
# <Noun phrase>

<One paragraph: the idea in plain language, before any jargon.>

## The problem

<What goes wrong without this. Be concrete.>

## How AgentArea approaches it

<The model. One diagram if it earns its place.>

## Why not <the obvious alternative>

<The tradeoff. This section is what separates a concept page from marketing.>

## Limits

<What this does not do. Especially for anything security-adjacent.>

## Related

<Links to the guides that put this into practice.>
```

Constraints:

- **No step-by-step instructions.** Link to the guide.
- **State the tradeoff.** A concept page that only lists benefits is a landing
  page. The "Why not X" section is mandatory for anything architectural.
- **State the limits.** For sandbox and governance pages this is not optional:
  readers make security decisions from these pages.

## Reference

Information-oriented. The reader knows what they are looking for and wants it
fast.

```markdown
# <Exact name of the thing>

<One sentence. What it is.>

## Synopsis

<Signature, endpoint, or schema.>

## Parameters

| Name | Type | Default | Description |
|---|---|---|---|

## Returns / Response

## Errors

| Code | Meaning | Action |
|---|---|---|

## Example

<Minimal and complete. One example, not a tour.>
```

Constraints:

- **Dry on purpose.** No narrative, no encouragement, no "simply".
- **Complete over readable.** Every parameter, including the ugly ones.
- **Structurally uniform.** Every page in `reference/` has the same headings in
  the same order, so the eye learns where to jump.
- **Generated where a generator exists.** API reference comes from OpenAPI. A
  hand-written endpoint table is a future lie.

---

## Splitting an overgrown page

Trigger: a page over ~8 KB, or one whose headings answer more than one of
"teach me / help me / why / what are the parameters".

1. **Outline and tag.** List every H2 with its genre.
2. **Find the seam.** Usually the page is one genre for the first third and
   another for the rest.
3. **Name the new pages** and place them via `information-architecture.md`.
4. **Grep for inbound links** before touching anything:
   ```bash
   cd docs && grep -rn "old-slug" --include="*.md" --include="*.json" .
   grep -rn "docs/old-slug" ../agentarea-webapp/src ../README.md
   ```
5. **Split, then update `docs.json`**, then add redirects for the old slug.
6. **Run `./validate-docs.sh`.**

Worked example — `monitoring.md`, 31 KB:

| Headings about | Genre | New home |
|---|---|---|
| What to observe and why | C | `concepts/execution/events` (partial) |
| Wiring Prometheus/Grafana | G | `self-host/observability` |
| Metric names and labels | R | `reference/metrics` |
| Log fields and levels | R | `reference/logging` |
| "Nothing is showing up" | G | `self-host/troubleshooting` |
