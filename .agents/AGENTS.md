# AGENTS.md — Agent Skills and Notes

This directory is the shared, harness-neutral home for agent instructions. It is
tracked in git so the whole team gets the same skills, not just whoever wrote
them.

```
.agents/
  skills/aa-<name>/SKILL.md        the skill itself
  skills/aa-<name>/agents/openai.yaml   surfaces the skill in Codex
  notes/YYYY-MM-DD-<topic>.md      durable decision records
```

`.claude/skills` is a symlink to `skills/`, so Claude Code discovers the same
files. Codex reads `.agents/skills` directly. Nothing in `.agents/` may depend on
which of the two is running.

## Skill rules

**Namespace.** Every project skill is named `aa-<name>`. Developers run with
dozens of global skills installed; an unprefixed `code-review` collides with
whatever else is on their machine.

**Harness independence is a hard requirement.** A skill may assume a POSIX shell
and this repository. It may not assume anything else:

- Give shell commands and written procedures. Do not name a harness's built-in
  slash commands, subagent types, or tool names — `/code-review`, `Task`,
  `Agent`, `oh-my-claudecode:executor` do not exist outside Claude Code.
- Parallelism is an optimization, never a requirement. Where fan-out helps, say
  so and state the fallback: "if parallel subagents are unavailable, cover the
  same ground yourself."
- Reference repository files by path relative to the skill, so the links resolve
  from any tool: `../../../AGENTS.md`, not `@AGENTS.md`.

**Ground every claim in a file.** A skill that says "run the linter" rots the
first time the linter changes. A skill that says "CI's `platform-lint` job runs
`uv run ruff check .`, `uv run ruff format --check .`, and `uv run pyright`
(`.github/workflows/ci.yml`)" tells the reader where to check when it drifts.
Cite the workflow, makefile, or source file that makes the statement true.

**Skills are guidance, not checklists.** State what to verify and why it matters;
leave judgment to the reader. Prefer one substantiated finding over a list of
nits.

**Codex surfacing.** Each skill carries `agents/openai.yaml`:

```yaml
interface:
  display_name: "AgentArea Pre-Push Checks"
  short_description: "Run the relevant AgentArea checks before push"
  default_prompt: "Use $aa-pre-push-checks before pushing this branch."
```

## Notes

Notes are decision records: what was decided, what was rejected, and why. They
capture the rationale that the diff cannot — an implementation shows what the
code does, never which alternatives were weighed.

Name them `YYYY-MM-DD-<topic>.md`. Write in present tense once the decision has
shipped. When a note is superseded, say so at the top and link the note that
replaces it rather than editing history away.

Notes are not authority. A note records the reasoning available when it was
written; disagreeing with one is a design discussion, not a rule violation.
