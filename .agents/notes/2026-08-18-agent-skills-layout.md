# Agent skills live in `.agents/`, shared through git

**Date:** 2026-08-18

## Context

Agent instructions for this repo were scattered and unshared. `.claude/` and
`.agents/` were both in `.gitignore`, so every skill anyone wrote stayed on the
machine that wrote it — a fresh clone or a second worktree got nothing. One
checkout had 33 skills under `.agents/skills/`, of which exactly one
(`deploy-to-staging`) was written for this project; the rest were an SEO/marketing
pack pulled in by a skill installer, already present globally. Its
`.claude/skills/` had drifted into a mix of 18 symlinks into `.agents/skills` and
6 real directories, so `deploy-to-staging` existed as two copies that could
disagree. A dead symlink, `agentarea-event-service/skills/golang-pro`, pointed at
a skill that exists nowhere.

The team also runs more than one harness — Claude Code and Codex both — so a
layout that only one of them can read is not viable.

## Decision

`.agents/` is the shared, harness-neutral home for skills and notes, and it is
tracked in git.

```
.agents/
  AGENTS.md                        rules for writing skills and notes
  skills/aa-<name>/SKILL.md
  skills/aa-<name>/agents/openai.yaml
  notes/YYYY-MM-DD-<topic>.md
.claude/skills -> ../.agents/skills
```

`.gitignore` became `.claude/*` plus `!.claude/skills`, and the `.agents` entry
was dropped.

Three properties follow:

- **One copy of every skill.** `.claude/skills` is a symlink, so Claude Code and
  Codex read the same files. Divergent duplicates are not representable.
- **`.agents/` stays clean.** Per-developer Claude state — `settings.local.json`,
  `worktrees/`, `commands/` — remains in `.claude/` and stays ignored.
- **New clones and worktrees get the skills.** This was the actual failure: the
  worktree this note was written in had no skills at all.

## Alternatives rejected

**Symlink `.claude` to `.agents` wholesale.** Simpler in `.gitignore` — a single
tracked symlink — and it matches the existing `CLAUDE.md -> AGENTS.md` at the
repository root. Rejected because every file Claude Code writes into `.claude/`
then lands inside the harness-neutral directory, and each would need its own
ignore rule. `settings.local.json` alone is 43 KB of machine-local state. The
directory that is supposed to be neutral would fill with one harness's artifacts.

**Keep everything in `.claude/skills/`, no `.agents/`.** Rejected: it locks the
skills to one harness, and the global setup on developer machines already uses
the `.agents` convention.

**Publish the whole existing skill set.** Rejected. The SEO/marketing pack is
installed globally already, has nothing to do with this codebase, and this
repository is public. Only project skills get committed.

## Skills in the first pass

- `aa-pre-push-checks` — maps the diff through the same `paths-filter` CI uses,
  then names the exact command each triggered job runs.
- `aa-code-review` — this repo's invariants: workspace scoping, event
  persistence, selector-vs-additive extension points, migration rules, generated
  frontend contracts.
- `aa-docs` — moved in from a developer's global skill directory, where the team
  could not see it.

The `aa-` prefix is deliberate: developers run with dozens of global skills, and
an unprefixed `code-review` collides with whatever else is installed.

Skills must not name a harness's slash commands, subagent types, or tool names —
those do not exist outside the harness that defines them. Parallelism is stated
as an optimization with an explicit sequential fallback. The full rules are in
[`../AGENTS.md`](../AGENTS.md).

## Consequence worth acting on

Writing `aa-pre-push-checks` required reading `ci.yml` against
`scripts/preflight.sh`, and they disagree. preflight skips `pyright` while
claiming in a comment that CI does not enforce it — CI does, in `platform-lint`,
with no `continue-on-error`. preflight runs `pytest tests/unit tests/functional`
where CI runs the much wider `make test`. And `migrations-gate`, `cli-test`,
`events-lint-test`, `version-check`, and `platform-build` are not covered at all,
which makes `agentarea-event-service` and `agentarea-cli` invisible to it.

The skill documents these gaps so nobody trusts a green preflight, but that is a
workaround. Fixing `scripts/preflight.sh` is the real repair.
