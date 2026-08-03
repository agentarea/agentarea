---
title: The policy engine
type: concept
summary: How policy rules compile into one immutable effective-policy snapshot per task, and where the administration, decision and enforcement points live in the code.
prerequisites:
  - /concepts/governance/authorization-basics
related:
  - /concepts/governance/the-agentarea-model
  - /concepts/governance/tool-authorization
  - /concepts/governance/budgets-and-quotas
  - /concepts/governance/approvals
last_updated: 2026-07-29
---

# The policy engine

The policy engine decides what a running task may do: which tools it may call,
how much it may spend, how many tokens it may burn, what needs a human, and which
content filters run. It is separate from the
[resource graph](/concepts/governance/the-agentarea-model), which decides who may
touch which object. The graph answers *who owns this*; the policy engine answers
*what may this run do*.

Its output is a single immutable snapshot per task — the effective policy — that
every enforcement point in the run reads. Nothing consults the rule table at
runtime.

## The problem

Governance intent arrives from several directions at once. A workspace has a
monthly spend cap. An agent is restricted to a subset of tools. A particular user
is not allowed to send email through any agent. A single task is launched with a
tighter budget than usual.

If each of those is enforced by its own mechanism, two things go wrong. Different
enforcement points disagree — the tool list shown to the model includes something
the gate will reject, so the agent burns a turn on a call that can only fail. And
a lower scope can accidentally *loosen* a higher one, so a per-task setting
quietly raises a workspace ceiling.

## How AgentArea approaches it

One rule shape, four layers, one snapshot.

### Administration: rules

A `PolicyRule` row is one governance intent for one subject:

| Field | Meaning |
|---|---|
| `subject_type` | `workspace`, `agent`, `user`, or `group` |
| `subject_id` | the id of that subject |
| `target` | selector: `tool:<name>`, `spend`, `service`, `tokens`, `content`, `mcp:<id>`, `model:<id>`, `skill:<id>`, `collection:<id>`, or `*` |
| `effect` | `allow`, `deny`, `cap`, `approval`, `safety`, or `egress` |
| `params` | effect-specific values, for example `{"amount_usd": "50.00", "period": "run"}` |
| `condition` | an optional expression string |
| `enabled`, `priority` | row state |

Rules are managed through `/v1/policies` (list, create, get, patch, delete), and
every mutation is recorded in the audit log as `governance_policy.create`,
`.update`, `.set_enabled` or `.delete`. A malformed target selector is rejected
at parse time rather than silently ignored.

New workspaces are seeded from `config/default_policies.yaml`, which is data
rather than a code constant: a 500.00 USD monthly spend cap, a 50.00 USD per-run
cap, 20,000,000 total tokens, 100,000 tokens per call, and both content-safety
filters on. Seeding is idempotent per dimension — a cap the user already set is
left alone while the rest of the baseline is filled in — and no approval rule is
included, so human-in-the-loop is opt-in.

### Resolution: four layers, tighten-only

At task creation, `GovernancePolicyResolver` reads the enabled rules for each
subject layer, compiles each layer into a typed `PolicyDocument`, and merges them
in order:

```
workspace  →  agent  →  user  →  task
```

The user layer resolves from the *task creator*, which is what makes the same
agent produce different verdicts for different callers.

The merge is monotonic. Money and integer ceilings take the minimum; denied tool
lists union; booleans OR together. A lower layer that tries to loosen a higher one
does not silently win — `PolicyResolver` raises `PolicyValidationError`, and the
preview endpoint surfaces it as HTTP 422. Concretely, a lower scope cannot raise a
spend or token ceiling, cannot widen an allowlist beyond its parent's patterns,
cannot set `requires_human_approval` back to false, and cannot disable a content
filter its parent enabled.

The result is an `EffectivePolicy`: the merged document plus `source_policy_ids`
and a `resolver_version` (`policy-resolver-v1`). You can compute one without
committing to a task through `POST /v1/governance/effective-policy/preview`.

### The snapshot

The effective policy is resolved once, at task creation, and carried into the
Temporal workflow as state. It is not persisted to a database table;
`GET /v1/governance/task-policy-snapshots/{task_id}` serves it by querying the
task's workflow. A task that is not running has no snapshot to return.

That snapshot is translated into a flat `execution_state` dictionary for the
interceptor gates — `budget_usd`, `service_budget_usd`, `max_tokens`,
`tools_config`, `escalation_rules`, `content_safety` — alongside the runtime
counters (`cost_used`, `service_cost_used`, `tokens_used`) so a gate compares
against a running total rather than only a ceiling. Money crosses that boundary as
a float because the gates do ratio arithmetic; authoritative accounting stays in
`Money` (Decimal) upstream.

### Decision and enforcement points

| Role | Where |
|---|---|
| **PAP** — where policy is written | `/v1/policies`, `GovernancePolicyService`, `config/default_policies.yaml` |
| **PDP** — where the verdict is computed | `decide_tool_policy` for tool verdicts; each interceptor gate for its own dimension |
| **PEP** — where the verdict is applied | tool disclosure in the workflow, the workflow tool gate, the tool activity, the MCP proxy, task creation, and the Temporal activity interceptor |

The interceptor pipeline is the generic half. Interceptors register against a
phase (`pre_llm_call`, `post_llm_call`, `pre_tool_call`, `post_tool_call`,
`tool_discovery`) with a priority, and fall into three categories the pipeline
treats differently:

- **Gates** decide. A `DENY` or `ESCALATE` stops the chain and returns.
- **Filters** transform. A `MODIFY` rewrites the content that later interceptors
  and the caller see; a `DENY` stops the chain.
- **Observers** watch. Their results are ignored and their exceptions swallowed.

The worker registers this pipeline as a Temporal worker interceptor. On the way
into `call_llm`, `execute_mcp_tool` and `discover_available_tools` it runs the
pre-phase; on the way out it runs the post-phase and applies any content
modification to the activity's output. A `DENY` becomes a `GovernanceDenied`
exception; an `ESCALATE` becomes `EscalationRequired`.

The registered set today is: `CostBudgetGuard` (priority 100, pre-LLM and
pre-tool), `ServiceBudgetGuard` (105, pre-tool), `TokenBudgetGuard` (110,
pre-LLM), `PromptInjectionDetector` (300, pre-LLM), `OutputSanitizer` (300,
post-LLM and post-tool), `MCPToolSecurityScanner` (300, tool discovery),
`SemanticGuard` (400, pre-tool), and the two observers at 800 and 810 on every
phase. Enterprise builds can inject an entitlement guard at 120 through the
extension registry.

## Why not a general policy language

The obvious alternative is to express governance as OPA/Rego or CEL policies and
evaluate them at each decision point. AgentArea does not, for one reason: a
general expression engine is a second authority.

The value of the current design is the monotonic merge. Because every dimension is
a typed field with a known combination rule — minimum for ceilings, union for
denials, OR for flags — the resolver can *prove* that a lower scope only tightens,
and reject a rule that would not. An arbitrary boolean expression has no such
lattice. Two Rego policies cannot be merged into a snapshot; they can only both be
evaluated, and then "which one wins" becomes a runtime question that neither the
UI nor the audit trail can answer ahead of time.

The cost is expressiveness, and it is a real cost. Anything that is not one of the
compiled dimensions cannot be expressed at all, and the `condition` column exists
precisely because that limit is felt — see below.

## Limits

- **`condition` is stored and never evaluated.** Every `PolicyRule` carries a
  `condition` string. It round-trips through the API and the repository and is
  returned to clients, but nothing in the resolver, the compiler or any gate reads
  it. A rule with a condition behaves exactly as if the condition were absent.
- **Several effect and target combinations compile to nothing.** The compiler
  handles `cap` on `spend`/`service`/`tokens`, `allow`/`deny` on a *named* tool,
  `approval`, and `safety` on `content`. Everything else is skipped and logged at
  debug level. In particular, `deny` on `mcp:<id>`, `model:<id>`, `skill:<id>` or
  `collection:<id>` is stored, returned by the API, and has no runtime effect. So
  is `allow` or `deny` on `tool:*`.
- **`group` rules are never resolved.** `PolicySubjectType` includes `group`, and
  a group-scoped rule can be created through the API. The resolver reads the
  workspace, agent and user layers only, so those rows never reach a snapshot.
- **`egress` rules are data only in core.** They are stored, round-tripped, and
  readable through a helper, and they deliberately do not compile into the runtime
  document. Core does not enforce a container network boundary; that is an
  enterprise component. A helper exists to read the allowlists and has no caller
  in this repository. An egress rule in an open-source deployment restricts
  nothing.
- **The snapshot is frozen at task creation.** Changing a rule does not affect a
  task already running. There is no revocation path into a live workflow.
- **Two interceptors exist and are never registered.** `EscalationGuard` (glob
  matching against `escalation_rules`, returning escalate) and
  `ContentPolicyEnforcer` (denying configured prohibited content categories) are
  both implemented and tested, and neither appears in the pipeline the worker
  builds. `EscalationGuard`'s omission is deliberate and documented — approval is
  enforced in the workflow, which is the only layer that can pause. Reading either
  file and assuming it runs would be wrong.
- **The pipeline swallows interceptor exceptions.** If a gate raises, the pipeline
  logs the traceback and continues to the next interceptor. A gate that crashes
  fails open for its own dimension.
- **`GET /v1/network/topology` reports a governance overlay that is hardcoded.**
  The interceptor list that endpoint returns is a static constant in the API, not
  a reading of the pipeline the worker builds. It advertises `escalation_guard`
  and `content_policy_enforcer`, neither of which is registered, and its phase
  lists disagree with the real registrations for `semantic_guard`,
  `prompt_injection_detector`, `output_sanitizer` and `mcp_tool_scanner`. Treat
  it as a diagram, never as evidence that a control is running.
- **The observers record nothing outside the process.** `MetricsObserver`
  increments an in-memory dictionary that nothing exports, and `AuditObserver` is
  constructed without an event sink, so it logs at debug level and publishes
  nothing. The `SecurityFinding` event type is defined and never emitted by any
  interceptor. Governance decisions are observable through task events and
  application logs, not through these.
- **Two phases have no interceptors.** `pre_delegation` and `post_delegation`
  exist in the `Phase` enum, but nothing registers against them and the Temporal
  bridge maps only three activities — `call_llm`, `execute_mcp_tool` and
  `discover_available_tools`. Agent delegation passes through no pipeline phase.
- **Two of the three registered gate dimensions have a second counter.** Run
  budget and service budget are tracked both by the in-workflow `BudgetTracker`
  and by the gates reading `execution_state`. See
  [budgets and quotas](/concepts/governance/budgets-and-quotas) for what that
  duplication means in practice.

## Related

- [Tool authorization](/concepts/governance/tool-authorization) — the tool half of
  the PDP, and its enforcement points.
- [Budgets and quotas](/concepts/governance/budgets-and-quotas) — the spend and
  token dimensions in detail.
- [Approvals](/concepts/governance/approvals) — the one dimension that pauses a
  workflow.
- [The AgentArea model](/concepts/governance/the-agentarea-model) — the other
  authorization surface.
