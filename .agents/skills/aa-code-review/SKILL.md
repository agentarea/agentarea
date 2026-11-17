---
name: aa-code-review
description: Use when reviewing a pull request or a working diff in the agentarea repo — orients the reviewer to this codebase's invariants (workspace scoping, event persistence, extension-point selection, migration rules, generated frontend contracts) and the review-specific checks that neither CI nor reading the diff alone can establish.
---

# Reviewing an AgentArea Change

**This is guidance, not a checklist.** Read the diff and enough surrounding code
to understand the design before judging it. Prioritize correctness, workspace
isolation, and broken required behavior over style. One substantiated blocker
beats a list of nits.

Start by establishing the real scope against the live base:

```sh
git diff --stat "$(git merge-base HEAD origin/main)"...HEAD
```

Re-establish the base after a retarget or a merge; a stale diff makes you review
code that is no longer proposed.

## Sources of truth

- [`AGENTS.md`](../../../AGENTS.md) — repository layout and cross-cutting
  anti-patterns.
- [`agentarea-platform/internal/kernel/README.md`](../../../agentarea-platform/internal/kernel/README.md)
  and [`agentarea-platform/tools/archgen/main.go`](../../../agentarea-platform/tools/archgen/main.go)
  — kernel ports and the layering the lint enforces.
- [`agentarea-platform/internal/schema/README.md`](../../../agentarea-platform/internal/schema/README.md)
  — migration rules.
- [`agentarea-webapp/AGENTS.md`](../../../agentarea-webapp/AGENTS.md) — server
  actions, generated contracts, list-page and icon conventions.
- [`.agents/notes/`](../../notes/) — design rationale. Disagreeing with a note is
  a design discussion, not an automatic veto.

Verify the author ran the checks that
[`aa-pre-push-checks`](../aa-pre-push-checks/SKILL.md) selects for this diff, and
review the semantic gaps neither those nor CI can detect.

## Blocking requirements

1. **Workspace isolation holds.** A store queries only through the `db.Session`
   it is handed, which carries the workspace the call acts in; workspace-less
   tables go through `db.Global` (`agentarea-platform/internal/kernel/db`). A
   new `Global` use needs a reason. A query that reaches
   the database without workspace scoping is a cross-tenant data leak, not a
   style issue — trace the new query to the scoping that constrains it, and do
   not accept "the caller filters it" as the constraint.

2. **Events are persisted, not just published.** A domain event that goes to
   Redis pub/sub without a DB write disappears for anyone who was not listening.
   Three independent consumers read this stream — the webapp, A2A, and the CLI —
   so an event vocabulary change breaks surfaces the diff does not touch. Verify
   the CLI too; it has silently rotted on an invented vocabulary before.

3. **Failures are loud.** No silent fallback to a default when required config is
   absent, and no swallowed error. An error that is not returned is logged with
   its cause. Config that is missing fails at startup with a
   clear message rather than degrading into a surprising runtime mode.

4. **Extension points are additive.** Every `ext.With*` option
   (`agentarea-platform/ext/ext.go`) layers on: present means active, a failing
   factory stops the process, and registering a single-valued point twice is a
   startup error. A new option that silently overrides explicit config is the
   bug class this rule exists to prevent.

5. **Security dependencies are required, never optional.** Secret managers, auth,
   and encryption are constructor requirements, not `| None` parameters that
   degrade into an unprotected path when unset.

6. **Migrations are append-only goose files.** The next number in
   `agentarea-platform/internal/schema/migrations/` (`NNNNN_<slug>.sql`); a
   shipped file, `00001_baseline.sql` included, is never edited. Two branches
   taking the same number is the common failure after a merge — renumber the
   later one.

7. **Frontend contracts are generated, not written.** No hand-written type or Zod
   schema mirroring a backend contract, no `as any` on a response, no
   `fetch("/api/proxy/v1/...")` from the browser for JSON — that path is only for
   file download, streaming, SSE, and multipart. A new backend endpoint means
   `pnpm generate:api` ran in the same diff.

## Manual checks

- **Ownership boundaries.** Sandbox and MCP instance lifecycle belongs to the
  `mcp` and `sandbox` roles, with lease expiry rather than explicit delete.
  Reject code in other modules that starts, stops, or reaps a runtime.
- **Authorization vocabulary.** This project's model is ReBAC. Review describing
  it as RBAC signals the author is reasoning about the wrong model. Tool calls
  clear three distinct layers (disclosure, task-policy deny-by-default, and the
  grant check) plus a second enforcement path through the governance interceptor
  pipeline — a change to one layer that does not account for the others leaves a
  bypass.
- **Layering.** A module imports the kernel, itself and other modules' `api`
  only; `make -C agentarea-platform check` enforces it. A service built in a
  test but not wired in `agentarea-platform/app/` works in that test and
  nowhere else.
- **Worker reachability.** Code registered only in the API process is invisible
  to worker-run agents. When a diff adds a capability agents are supposed to use,
  confirm the worker can actually reach it.
- **Money.** Costs, budgets, and balances use `money.Decimal` from
  `agentarea-platform/internal/kernel/money`. A `float` anywhere in a monetary
  path is a rounding bug waiting for a large number.
- **Audit.** New audit events go through the governance module's audit service
  (`agentarea-platform/internal/modules/governance/service/audit.go`).
- **Test strength.** An assertion must fail on the regression it claims to guard.
  Tests that restate the implementation, or that mock the very boundary under
  test, prove nothing. For authorization and task-execution changes, a passing
  unit test is not sufficient evidence — those are done when a real task runs on
  a real agent.
- **Frontend test scope.** Never ask a UI diff for more tests; `vitest` is not a
  CI gate for the webapp, so tests added there are unenforced weight. A webapp
  change is proved by the surface running, or by one `tests/e2e/*.real.spec.ts`
  covering the flow — not by a jsdom assertion. Flag a new `*.test.tsx` that
  scrapes rendered markup (`renderToStaticMarkup` + `toContain` on a class,
  `id`, or `aria-label`), or that mocks the components and server actions the
  subject is built from and then asserts what the mocks produced: the fix is
  deleting it, or lifting the logic into a pure module that a `*.test.ts` can
  state. The full rule is `agentarea-webapp/AGENTS.md` §"TESTS (THIS DIR)".
- **Frontend state placement.** Flag a client component that loads backend data
  through a server action in `useEffect` (actions run one at a time per page, so
  it stalls every later save), or that mirrors server data and form fields in
  `useState` (`loading`/`loadError`/`reloadKey`, `editX` + `hasChanges`,
  `saving`/`saved`). The fix is the placement table in
  [`aa-webapp-ui`](../aa-webapp-ui/SKILL.md), not a reducer or a new store.
- **Comment and doc density.** Flag comments that narrate what the code plainly
  does. Comments earn their place by stating a non-obvious contract or the reason
  behind a surprising choice. Documentation under `docs/` follows the
  information-architecture rules in [`aa-docs`](../aa-docs/SKILL.md).

When the diff is large, splitting the survey across parallel reviewers helps —
give each one a subsystem and require evidence rather than impressions. If
parallel reviewers are unavailable, cover the same subsystems yourself in
sequence; do not let the first finding end the review.

## Reporting

State the defect, its location, its impact, and the evidence for it. Put a
localized defect inline on the tightest relevant range; use a top-level comment
for cross-cutting architecture or scope concerns. Separate blockers from
suggestions, and omit anything a green gate already enforces.

When receiving review, verify each claim and either fix it or rebut it on
technical grounds. Neither performative agreement nor reflexive defense is
useful.
