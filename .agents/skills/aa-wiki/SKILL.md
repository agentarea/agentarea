---
name: aa-wiki
description: Find, read and write AgentArea's organizational memory in the agentarea-wiki repo. Use before designing or changing a subsystem, before reopening a settled decision, when asked why something is built the way it is, when touching production or infra, and whenever a decision, its rationale or durable operational knowledge needs recording. Decisions go to the wiki, not to an agent's private memory, not to docs/, not to .agents/notes/.
---

# AgentArea Wiki

The wiki is the org's memory: what was decided, why, what was rejected, how the
system works, and what is still open. The code shows what exists. The wiki shows
why it exists, and what not to re-argue.

## Where it is

A separate repository, `git@github.com:agentarea/agentarea-wiki.git` (private),
checked out next to this one at `../agentarea-wiki`. If it is missing:

```sh
git clone git@github.com:agentarea/agentarea-wiki.git ../agentarea-wiki
```

Refresh it before reading with `git -C ../agentarea-wiki fetch`. Parallel
sessions edit the same checkout, so it is often dirty. If `git status` shows
other people's changes, read `origin/main` with
`git -C ../agentarea-wiki show origin/main:<path>` rather than pulling over
their work.

Its operating contract is `../agentarea-wiki/AGENTS.md`: source order, page
rules, confidence labels, navigation, maintenance loop. Read it before writing.

## How to read it

The wiki is a tree with one root. Walk it top-down:

1. `wiki/index.md`: the root. It lists the sections.
2. The section index: `architecture/index.md` (reading order and the page
   contract), `decisions/index.md` (every ADR, one row with the outcome and the
   status), `gtm/index.md`, `content/index.md`.
3. The page itself.

To find a subject without walking, search the text:

```sh
grep -rli "<term>" ../agentarea-wiki/wiki
```

When you rely on a page:

- **Architecture pages** carry `Verified against <sha> (<date>)`. Code newer than
  that may have moved, and when they disagree the code wins (source order in
  `../agentarea-wiki/AGENTS.md`). Say so instead of quoting the page as current.
- **ADRs** are superseded, never edited. Check the status column in
  `decisions/index.md`. A `Proposed` ADR is not built, and a superseded one names
  its successor.
- `unresolved/open-questions.md` and `unresolved/contradictions.md` hold what is
  not settled. Check them before presenting something as decided.

## When to write, and where

| What you have | Where it goes |
|---|---|
| A decision with rationale and rejected alternatives (shipped or proposed) | New ADR in `wiki/decisions/` |
| How a subsystem works now | The page in `wiki/architecture/`, plus a fresh `Verified against` |
| Release, deploy, incident or prod knowledge | `wiki/operations/` |
| An open question or two sources that disagree | `wiki/unresolved/` |

Not to an agent's private memory, where nobody else can read it. Not to `docs/`:
that is the published site, it states current behaviour only, and an ADR there
goes stale in public. Not to a new folder in this repo. `.agents/notes/` holds
three older notes and takes no new ones.

## How to write

- **ADR number:** one above the highest file in `wiki/decisions/`, counting
  untracked files. Another session may have taken the next number without
  committing yet:

  ```sh
  ls ../agentarea-wiki/wiki/decisions | grep -o '^ADR-[0-9]*' | sort | tail -1
  ```

- **ADR fields:** Date, Status, Related, then decision, context, rationale,
  rejected alternatives, implications, evidence (file paths, PRs, live checks),
  open questions. `ADR-0050-api-cors-any-origin.md` is a short complete example.
- **Wire it in the same commit:** a row in `decisions/index.md` (outcome in one
  sentence, plus status), and a link from the architecture page the decision
  changes. A page nothing links to will not be found.
- **Log it:** an entry in `logs/change-log.md` under today's `## YYYY-MM-DD`
  heading. Entries are in Russian; pages are in English.
- **Check it:** `python3 scripts/lint_links.py` from the wiki root must report
  zero broken links and zero unreachable pages.

## Committing

The wiki commits straight to `main`. The checkout is shared, so commit only what
you wrote:

- Stage by path, and use `git add -p` for files that also carry someone else's
  hunks (`decisions/index.md` and `logs/change-log.md` usually do).
- Review `git diff --cached` before committing. Push with `git push origin main`.
