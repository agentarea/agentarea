---
name: aa-docs
description: Write, place, and review AgentArea documentation. Use when adding or editing anything under docs/, deciding where a new page belongs, splitting an overgrown page, auditing docs against the information architecture, or documenting a new subsystem (sandbox, governance, MCP, triggers, execution). Enforces the page-type contract and the house style.
---

# AgentArea Documentation

Docs live in `docs/`, built by Mintlify, navigation declared in `docs/docs.json`.
A page that is not listed in `docs.json` is not published — adding the file is
half the work.

## The one rule

**Every page belongs to exactly one of four genres, and never mixes two.**

| Genre | Answers | Reader is | Directory |
|---|---|---|---|
| Tutorial | "teach me" | learning, has nothing working yet | `tutorials/` |
| Guide (how-to) | "help me do X" | working, has a specific goal | `guides/<object>/` |
| Concept | "why is it like this" | trying to understand | `concepts/<area>/` |
| Reference | "what are the parameters" | looking something up | `reference/` |

Mixing genres is the failure mode this codebase already has: `monitoring.md`,
`deployment.md`, `infrastructure.md` and `secrets-management.md` are each 20-31 KB
because they braid all four together. When a page passes ~8 KB, that is almost
always the reason — see `references/page-types.md` for how to split it.

Section names in `docs.json` are named after the reader's object ("Agents",
"Sandbox", "Governance"), never after the genre. Do not create top-level
`tutorials/how-to/reference/explanation` groups in the navigation — none of the
22 benchmarked doc sites do that. Diataxis is the discipline behind the shelf,
not the label on it.

## Operations

Pick the operation that matches the request: `place`, `write`, `audit`, or
`split`.

### place — "where does this page go?"

1. Read `references/information-architecture.md`.
2. Name the genre first, the section second. If you cannot name one genre, the
   page is really two pages.
3. Check whether an existing page already owns the topic — search for the title
   and two key nouns across `docs/*.md`. Extending beats adding.
4. Report the target path and the `docs.json` group to add it to.

### write — create a page

1. Establish genre and path via `place`.
2. Read the matching template in `references/page-types.md` and the frontmatter
   contract there. Fill every frontmatter field; `related` and `prerequisites`
   are not optional.
3. Read `references/house-style.md` before writing prose.
4. Ground every claim in the code. Do not describe intended behaviour: open the
   relevant file under `agentarea-platform/libs/`, `agentarea-mcp-manager/internal/`,
   or `agentarea-webapp/src/` and confirm. Cite config keys and endpoint paths
   exactly as they appear in source.
5. Add the page to `docs.json` in the correct group.
6. Run `cd docs && ./validate-docs.sh`.

### audit — review existing docs

Run the checks in `references/house-style.md` under "Audit checklist". Report
findings as a table of `file | genre it claims | genre it actually is | action`.
Do not rewrite during an audit; produce the list, then let the user pick.

### split — break up an overgrown page

1. Outline the page by heading, tagging each section with its genre.
2. Propose the split: which headings become which new pages, in which sections.
3. Confirm with the user before writing — splitting changes URLs, and every
   inbound link in `docs/` and in the webapp needs updating. Search for the old
   slug before you delete anything.

## Documenting a new subsystem

A subsystem is not documented until all four exist:

1. **Concept page** — the mental model and the tradeoff that produced it. Why
   this design and not the obvious alternative.
2. **At least one guide** — the single most common thing a user does with it.
3. **Reference** — every parameter, endpoint, env var, and default.
4. **A place in an existing tutorial** — or an explicit note that it is advanced
   and deliberately out of the learning path.

Ship the concept page first. A reference without a concept page is where
AgentArea docs currently fail readers most.

## Grounding sources

Do not guess at subsystem behaviour. Authoritative sources in this repo:

| Area | Where the truth lives |
|---|---|
| Sandbox control/data plane | `agentarea-mcp-manager/internal/sandbox{control,placement,runner}/` |
| MCP lifecycle, warm pool | `agentarea-mcp-manager/internal/{container,warmpool,mcpidle}/` |
| Governance, policy engine | `agentarea-platform/libs/governance/` (domain/, engines/, interceptors/) |
| Task execution | `agentarea-platform/libs/execution/`, `libs/tasks/task_service.py` |
| Events | `libs/common/.../events/`, plus the event-architecture ADR |
| API surface | the OpenAPI spec — regenerate, never hand-write endpoint tables |
| Decisions and rationale | `agentarea-wiki/wiki/decisions/` — read them, never publish them |

## Published vs internal

`docs/` contains exactly what Mintlify publishes. Nothing else belongs there.

Architecture decision records live in the wiki repo, not here — they are
point-in-time records that get superseded rather than updated, so publishing
them puts knowingly-stale statements on the site. Plans, internal audits and
test notes do not belong in `docs/` either.

Because the wiki is a separate private repo, a `docs/` page cannot link to an
ADR. Read the ADR for grounding, then state the reasoning in prose in the
"Why not X" section of the concept page. Never leave a dangling citation to a
path a reader cannot open.

## References

- `references/information-architecture.md` — the full section map and where each
  page goes. Read this before creating any page.
- `references/page-types.md` — frontmatter contract, per-genre templates, and
  the splitting procedure.
- `references/house-style.md` — voice, formatting, and the audit checklist.
- `references/benchmarks.md` — what 22 comparable doc sites do, and which
  pattern each AgentArea section is modelled on. Read before proposing
  structural changes so the research is not redone.
