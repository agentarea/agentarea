# ADR-005: Policy Engine as the Single Source of Truth for Governance

**Date:** 2026-06-01
**Status:** Accepted

## Context

Governance decisions about agent execution — which tools may be called, whether
a call needs human approval, budget/token ceilings, content-safety — were
spread across two places:

1. The **governance policy engine** (`libs/governance`): typed `PolicyDocument`
   resolved per scope chain (workspace → agent → task) into an immutable
   `TaskPolicySnapshot`, enforced at the Temporal activity boundary by gates.
2. **Ad-hoc config** scattered elsewhere: per-tool `requires_user_confirmation`
   in agent config, `goal.requires_human_approval` on the request.

This split meant a policy author could set an approval rule and have it silently
do nothing, while real approval was driven by config the policy engine never saw.
The principle we are adopting: **every governance decision flows through the
policy engine.** Ad-hoc mechanisms are removed, not kept in parallel.

There is no separate PDP class in the code, which has caused "where is the
decision point?" confusion. This ADR records the mapping explicitly.

## Decision

### 1. Reference-architecture mapping (XACML PAP/PDP/PIP/PEP)

The policy layer maps onto the standard access-control points. We deliberately
do **not** introduce dedicated `PolicyDecisionPoint` / `Decision` classes — the
existing pieces already play those roles:

| Point | Role | In this codebase |
|-------|------|------------------|
| **PAP** (administration) | author/store policy | `governance_policies` table, `GovernanceService`, `PUT /v1/governance/policies/{scope}/{id}`, `PolicyResolver` (scope-chain merge), `TaskPolicySnapshot` |
| **PIP** (information) | supply attributes for a decision | `InterceptorContext.execution_state` — the anti-corruption layer; carries the resolved policy plus runtime counters (cost/tokens) and the reconciled budget |
| **PDP** (decision) | evaluate policy → decision | `InterceptorPipeline` running the gates; each gate returns an `InterceptorResult` whose `InterceptorAction` (ALLOW/DENY/WARN/ESCALATE/MODIFY) **is** the typed decision |
| **PEP** (enforcement) | intercept + enforce | `GovernanceActivityInterceptor` (Temporal) for tool/LLM calls; the workflow loop for human approval |

Gates are intentionally **not** coupled to `EffectivePolicy` — they read the
flat `execution_state`, which keeps the interceptor framework generic and
extensible (`ExecutionInterceptor` protocol + `ExtensionRegistry`). The
translation `EffectivePolicy.to_execution_state()` is the ACL between the typed
policy domain and the generic framework.

### 2. Each policy type has its own composition algebra

`PolicyResolver` merges per dimension; the algebras differ by intent:

| Policy | Nature | Composition | Default |
|--------|--------|-------------|---------|
| Budget (run/service/monthly) | ceiling | `min` / tighten, anti-loosening | unlimited → cap |
| Token (max_tokens) | ceiling | `min` | unlimited |
| ContentSafety | safety toggle | only-stricter (OR of enabled) | configured |
| Approval / escalation | routing | union of rules | none |
| Tools | restriction (today) | allow tighten + deny union, deny-first | open |

The scope-chain merge + anti-loosening is a **ceiling** mechanism: a lower scope
can never loosen a higher one (org cap cannot be bypassed by a task policy). It
is correct for budget/token/content-safety/approval. It is **not** a grant
mechanism — see Deferred.

### 3. Human approval is policy-driven, enforced in the workflow

`ApprovalPolicy` (`requires_human_approval`, `escalation_rules`) is the single
source for "does this tool call need a human". It is evaluated **inside the
workflow loop** (`policy_requires_approval`), which is the only place that can
pause and resume:

`policy_requires_approval` → `HUMAN_APPROVAL_REQUESTED` event → `wait_condition`
→ `resolve_escalation` signal (`POST /v1/.../resolve-escalation`) → resume.

Consequences:

- The activity-boundary `EscalationGuard` is **removed** from the pipeline. An
  ESCALATE there could only fail the activity (an interceptor cannot pause a
  workflow); it was a dead-end. Escalation belongs in the workflow.
- The ad-hoc per-tool `requires_user_confirmation` and `goal.requires_human_approval`
  no longer drive approval. The policy engine is the only trigger.

### 4. Budget single source of truth

The loop-level PEP (`BudgetTracker`) and the call-level PEP (`CostBudgetGuard`)
are reconciled at workflow start via `resolve_effective_budget()` (tightest of
`request.budget_usd` vs `policy.run_budget_usd` wins). Two enforcement points
remain by design (graceful loop stop + hard call block) but read one number.

## Deferred (not in scope)

- **Per-principal "who" (capability / delegation).** Today authorization is
  scope-based only (workspace/agent/task); `user_id` rides in context but no gate
  reads it. A future capability dimension where an agent and a user are
  independent principals (an agent may hold permissions a user does not, and a
  user may delegate a bounded subset to an agent) is a **grant** algebra
  (default-deny, union of grants, delegation bounded by the delegator,
  deny-override) — fundamentally different from the ceiling merge above, so it
  cannot be expressed through `PolicyResolver`. It is a separate layer composed
  with the ceiling: `granted ∩ within-ceiling \ denied`.
- **ReBAC graph + tuples (Ory Keto).** Only needed for cross-workspace resource
  sharing, not for capability bounding. SpiceDB is not part of this stack.

## Status of the gates

- Tools (which) — enforced, policy-driven (`CapabilityGuard`).
- Budget / Token / ContentSafety — enforced, policy-driven, single-sourced.
- Approval — policy-driven, enforced via the workflow HITL.
- `SemanticGuard` still returns ESCALATE for destructive patterns at the activity
  boundary; that path has the same no-resume limitation and should be revisited
  (treat as DENY, or route to the workflow approval path) in follow-up.
