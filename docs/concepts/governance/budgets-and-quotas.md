---
title: Budgets and quotas
type: concept
summary: The three spend dimensions AgentArea bounds — inference cost, service cost and tokens — where each ceiling is enforced, and which configured limits nothing reads.
prerequisites:
  - /concepts/governance/policy-engine
related:
  - /concepts/governance/policy-engine
  - /concepts/governance/tool-authorization
  - /concepts/governance/audit
last_updated: 2026-07-29
---

# Budgets and quotas

An agent loop can spend money without bound. Each iteration makes an LLM call,
each call costs, and a loop that fails to converge repeats until something stops
it. AgentArea bounds three separate currencies: inference cost in USD, service
cost in USD for payments an agent makes on your behalf, and tokens.

Every ceiling is a policy dimension, resolved through the same
[monotonic merge](/concepts/governance/policy-engine) as everything else, so a
lower scope can only tighten what a higher one set.

## The problem

Budget enforcement fails in two directions.

Enforced only at admission, a budget stops new tasks and does nothing about the
one that is currently looping. Enforced only inside the loop, a workspace that has
already blown its monthly ceiling keeps accepting work as long as each individual
run is small.

The second problem is arithmetic. The loop tracks spend to decide whether to keep
iterating; the per-call gate tracks spend to decide whether to allow the next
call. If those two read different numbers, the one that is easier to satisfy is
the real limit, and the other is decoration.

## The dimensions and their ceilings

| Ceiling | Scope | Enforced at |
|---|---|---|
| `monthly_spend_cap_usd` | workspace, calendar month | task creation |
| `run_budget_usd` | one task | the workflow loop and the per-call gate |
| `service_budget_usd` | one task | the workflow loop and the pre-tool gate |
| `max_tokens` | one task | the pre-LLM gate |
| `max_tokens_per_call` | one call | nothing — see limits |

They are written as `cap` rules. `target: spend` with `params.period` of `month`
or `run` sets the two spend caps; `target: service` sets the service cap;
`target: tokens` sets both token values. A `cap` rule missing its amount is
skipped and logged rather than treated as zero.

The default baseline for a new workspace is 500.00 USD per month, 50.00 USD per
run, 20,000,000 total tokens and 100,000 tokens per call.

## Where each is enforced

### Monthly cap: admission

When a task is created, `TaskService._enforce_budget_cap` resolves the effective
policy, sums `total_cost` across the workspace's tasks from the first of the
current UTC month, and raises `BudgetCapExceededError` if the total has reached
the cap. No cap configured means no check.

That rejection reaches a client as HTTP 402 in problem+json, with
`code: budget_cap_exceeded` and the three numbers needed to explain it —
`current_mtd_usd`, `cap_usd` and `workspace_id` — so a caller can distinguish a
spend refusal from an authorization failure and show how far over the cap the
workspace is.

This is admission control only. Crossing the monthly cap does not interrupt tasks
already running, and the month-to-date figure comes from persisted task costs, so
spend from a task still in flight is not fully counted until it finishes.

### Run budget: two enforcement points, one number

The per-task USD budget has two enforcement points, and they are reconciled
deliberately.

`resolve_effective_budget` takes the *minimum* of the budget on the task request
and the policy's `run_budget_usd`. That single number configures the workflow's
`BudgetTracker`, which decides whether the loop continues, and the same policy
value reaches `CostBudgetGuard` through the flattened `execution_state`. Neither
source can loosen the other.

`CostBudgetGuard` runs at both `pre_llm_call` (priority 100) and `pre_tool_call`
(also 100). It compares consumed cost against the budget: `WARN` at 80 percent,
`DENY` at 100 percent. A denial at the activity boundary raises
`GovernanceDenied`, which fails the activity.

If nothing is configured at all, `BudgetTracker` falls back to a default of
10.00 USD per run, and its warning threshold is 80 percent.

### Service budget

Service spend — payments an agent makes through a paid tool — is tracked
separately from inference cost. `ServiceBudgetGuard` runs at `pre_tool_call`
(priority 105) with the same thresholds: warn at 80 percent, deny when exhausted.
`BudgetTracker` maintains the matching counters in the workflow, where a limit of
zero or less means unlimited.

### Tokens

`TokenBudgetGuard` runs at `pre_llm_call` (priority 110), warning at 85 percent of
`max_tokens` and denying at 100 percent.

## How the numbers reach the gates

The gates do not read policy objects. The effective policy is flattened into a
plain dictionary — `budget_usd`, `service_budget_usd`, `max_tokens`,
`tools_config`, `escalation_rules`, `content_safety` — and the runtime counters
the activity request carries (`cost_used`, `service_cost_used`, `tokens_used`) are
merged into it before each phase runs.

Money crosses that boundary as a float, on purpose. The gates do ratio arithmetic
against running counters, and mixing `Decimal` with `float` there would raise
inside the gate — where the pipeline swallows the exception and the guard would
silently stop guarding. Authoritative money accounting stays in `Money` (Decimal)
in `BudgetTracker` and upstream of it.

## Why not a central quota service

The obvious alternative is one counter service that every component increments and
consults, so there is exactly one number. AgentArea does not have one, for a
structural reason: the loop check and the call check are asked at different times
and need different guarantees.

The loop decision has to be deterministic. It runs inside a Temporal workflow,
which replays its history on recovery, so it cannot make a network call to a
counter service — the answer would differ between the original run and the replay
and break determinism. The per-call decision runs inside an activity, where IO is
allowed but where the value must already be in the request for the interceptor to
see it.

The design that survives that constraint is: resolve one ceiling, carry it in the
snapshot, and have both points enforce the same number. What it costs is that
counters are per-task and local. There is no cross-task, real-time spend counter,
which is why the monthly cap is checked at admission against the database rather
than continuously.

## Limits

- **`max_tokens_per_call` is configured and never enforced.** It is a field on the
  token policy, it is merged monotonically across scopes, it is in the default
  workspace baseline at 100,000, and it appears in the API. It is not written into
  `execution_state` and no gate reads it. A single call may exceed it freely.
- **The monthly cap is admission-only.** A task that starts under the cap runs to
  completion regardless of how far past the cap the workspace goes, and concurrent
  task creation can cross it — the check is a read-then-decide with no lock.
- **A budget denial fails the activity.** `CostBudgetGuard` denying at
  `pre_tool_call` raises `GovernanceDenied` rather than returning a message the
  model can respond to. The graceful path — the loop noticing exhaustion and
  completing — comes from `BudgetTracker`, not from the gate.
- **A guard that crashes stops guarding.** The pipeline catches exceptions from an
  interceptor, logs the traceback and moves on. Failure of a budget gate is
  fail-open for that dimension.
- **Unconfigured means unlimited.** Each guard allows unconditionally when its
  ceiling is absent or not greater than zero. A workspace whose default policies
  were removed has no token ceiling and no service ceiling.
- **Cost figures depend on the provider.** Per-call cost is read from the LLM
  response where the provider supplies it, and estimated at a flat rate per token
  when it does not. A budget is therefore as accurate as the upstream cost
  reporting.
- **There are no rate or concurrency quotas.** Core bounds spend and tokens. It
  does not bound requests per second, concurrent tasks per workspace, or tool
  calls per minute. Anonymous or public execution has no quota of its own.
- **Nothing writes budget events to the audit log.** Budget warnings and denials
  appear in the task event stream and in logs, not in `audit_events`. See
  [audit](/concepts/governance/audit).

## Related

- [The policy engine](/concepts/governance/policy-engine) — how ceilings merge and
  where the snapshot comes from.
- [Tool authorization](/concepts/governance/tool-authorization) — the other gates
  sharing the pre-tool phase.
- [Audit](/concepts/governance/audit) — what is and is not recorded.
