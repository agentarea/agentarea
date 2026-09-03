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
- [`agentarea-platform/AGENTS.md`](../../../agentarea-platform/AGENTS.md) — DDD
  layering, DI, extension points, alembic rules.
- [`agentarea-webapp/AGENTS.md`](../../../agentarea-webapp/AGENTS.md) — server
  actions, generated contracts, list-page and icon conventions.
- [`agentarea-mcp-manager/AGENTS.md`](../../../agentarea-mcp-manager/AGENTS.md) —
  Go service conventions.
- [`.agents/notes/`](../../notes/) — design rationale. Disagreeing with a note is
  a design discussion, not an automatic veto.

Verify the author ran the checks that
[`aa-pre-push-checks`](../aa-pre-push-checks/SKILL.md) selects for this diff, and
review the semantic gaps neither those nor CI can detect.

## Blocking requirements

1. **Workspace isolation holds.** Every repository takes a `UserContext`; every
   persisted model carries `WorkspaceScopedMixin`; services receive a
   `RepositoryFactory` rather than constructing sessions. A query that reaches
   the database without workspace scoping is a cross-tenant data leak, not a
   style issue — trace the new query to the scoping that constrains it, and do
   not accept "the caller filters it" as the constraint.

2. **Events are persisted, not just published.** A domain event that goes to
   Redis pub/sub without a DB write disappears for anyone who was not listening.
   Three independent consumers read this stream — the webapp, A2A, and the CLI —
   so an event vocabulary change breaks surfaces the diff does not touch. Verify
   the CLI too; it has silently rotted on an invented vocabulary before.

3. **Failures are loud.** No silent fallback to a default when required config is
   absent, and no swallowed exception. An `except` clause that does not re-raise
   logs with `exc_info=True`. Config that is missing fails at startup with a
   clear message rather than degrading into a surprising runtime mode.

4. **Extension points are classified.** A new `agentarea.extensions` entry point
   is either a **selector** (exactly one active implementation, chosen by
   explicit config, extension is only a fallback, resolved implementation is
   logged) or **additive** (layers on, "installed ⇒ active" is correct). An
   installed selector extension silently overriding explicit config is the bug
   class this rule exists to prevent. Selector wiring lives in both
   `apps/api/.../main.py` and `apps/worker/.../main.py` — check both moved
   together.

5. **Security dependencies are required, never optional.** Secret managers, auth,
   and encryption are constructor requirements, not `| None` parameters that
   degrade into an unprotected path when unset.

6. **Migrations are self-contained and single-headed.** ISO-timestamp filename
   (`YYYYMMDD_HHMM_<slug>.py`), revision id ≤ 32 characters
   (`alembic_version.version_num` is `VARCHAR(32)`), `down_revision` pointing at
   the real head, no imports from `agentarea_common` or any domain lib. The
   letter-pair scheme is retired; do not extend it. Two heads after a merge is
   the common failure — it needs a merge revision, not a renamed file.

7. **Frontend contracts are generated, not written.** No hand-written type or Zod
   schema mirroring a backend contract, no `as any` on a response, no
   `fetch("/api/proxy/v1/...")` from the browser for JSON — that path is only for
   file download, streaming, SSE, and multipart. A new backend endpoint means
   `pnpm generate:api` ran in the same diff.

## Manual checks

- **Ownership boundaries.** The Python platform does not control sandbox or MCP
  instance lifecycle; the Go manager owns it, with lease expiry rather than
  explicit delete. Reject platform code that starts, stops, or reaps a runtime.
- **Authorization vocabulary.** This project's model is ReBAC. Review describing
  it as RBAC signals the author is reasoning about the wrong model. Tool calls
  clear three distinct layers (disclosure, task-policy deny-by-default, and the
  grant check) plus a second enforcement path through the governance interceptor
  pipeline — a change to one layer that does not account for the others leaves a
  bypass.
- **Layering.** `libs/` never imports from `apps/`. Domain → application →
  infrastructure, not the reverse. A service constructed without DI registration
  works in the test that constructs it directly and nowhere else.
- **Worker reachability.** Code registered only in the API process is invisible
  to worker-run agents. When a diff adds a capability agents are supposed to use,
  confirm the worker can actually reach it.
- **Money.** Costs, budgets, and balances use `Money` from
  `agentarea_common.money`. A `float` anywhere in a monetary path is a rounding
  bug waiting for a large number.
- **Audit.** New audit events go through `agentarea_common.audit`
  (`AuditService`, `@audited`), not the legacy `audit_logger`.
- **Test strength.** An assertion must fail on the regression it claims to guard.
  Tests that restate the implementation, or that mock the very boundary under
  test, prove nothing. For authorization and task-execution changes, a passing
  unit test is not sufficient evidence — those are done when a real task runs on
  a real agent.
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
