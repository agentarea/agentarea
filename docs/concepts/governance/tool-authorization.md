---
title: Tool authorization
type: concept
summary: The layers a tool call clears before it runs — composition, disclosure, the workflow gate, the activity re-check and the interceptor pipeline — and the default-allow posture at the centre of them.
prerequisites:
  - /concepts/governance/policy-engine
related:
  - /concepts/governance/the-agentarea-model
  - /concepts/governance/approvals
  - /concepts/governance/audit
  - /concepts/governance/budgets-and-quotas
last_updated: 2026-07-29
---

# Tool authorization

A tool call in AgentArea passes through several checks, and they are not the same
check. Composition decides what the agent physically has. Policy decides what it
may use. Disclosure decides what the model is even told about. Understanding
which layer rejected a call is the difference between fixing a policy rule and
fixing an agent configuration.

The relationship between them is a nesting:

```
Equipped  ⊇  Authorized  ⊇  Disclosed
(composed)   (policy)       (offered to the model)
```

Composition is candidacy, not permission. Policy is the authorization. Disclosure
is what actually reaches the prompt.

## The problem

The failure this design exists to prevent is disclosure and enforcement
disagreeing. If the model is offered a tool the gate will reject, the agent spends
a turn calling it, receives an error, and often retries — burning budget on a call
that could never succeed and polluting the context with a capability it does not
have.

The second failure is many enforcement points each answering the question their
own way. A tool reached through the workflow, through the MCP proxy and through a
direct activity invocation must get the same verdict, or the strictest path is
decorative.

## The layers a call clears

### 1. Composition

What the agent is equipped with: its MCP server instances' exposed tools, its
skills, its code tools, its delegation targets, plus anything added at task
creation. This is not an authorization decision. A tool the agent is not composed
with is absent from the run entirely — there is nothing to deny.

### 2. Disclosure

Before each LLM call the workflow runs `filter_disclosed_tools` over the composed
list. It drops every tool the policy decision returns `DENY` for and keeps the
ones needing approval, because those escalate to a human rather than fail.

A fixed set of control-flow tools is always disclosed regardless of policy:
`completion`, `task_complete`, `request_user_input`, `recall_history`,
`read_tool_output`, `activate_tool_source` and `load_tools`. They reach no
external system and are never gated on execution. Without `completion` an agent
could never finish, and without `request_user_input` it could never ask — so a
restrictive policy must not be able to strand a run.

### 3. The workflow gate

`_gate_tool_call` runs the policy decision again before every capability tool
call, and it covers all three execution paths: MCP and code tools, skill
activation, and agent delegation. On `DENY` it appends a tool message saying the
call was denied and emits a `tool.result` event carrying
`denied_by_policy: true`, so the model sees the outcome and the event stream
records it. On `REQUIRE_APPROVAL` it hands off to the
[approval flow](/concepts/governance/approvals).

This is the only enforcement point that can pause. Everything downstream of it
runs inside a Temporal activity, and an activity cannot wait for a human.

### 4. The activity re-check

`execute_mcp_tool_activity` calls the same predicate a third time before touching
anything. A `DENY` returns a denial result. A `REQUIRE_APPROVAL` at this point is
also a denial — the reason string says the approval must be resolved before
activity execution — because reaching the activity with an unresolved escalation
means the workflow gate was bypassed.

### 5. The MCP proxy

Tool calls that arrive over HTTP rather than through a workflow — an external MCP
client talking to `POST /v1/mcp/{instance_id}/mcp` — clear the same predicate.
`_authorize_mcp_tool_calls` parses the JSON-RPC body, extracts every `tools/call`
method, resolves the workspace and user policy layers at request time (there is no
task snapshot here), and returns HTTP 403 for anything not allowed.

### 6. The interceptor pipeline

Independently of the policy decision, the Temporal activity interceptor runs the
governance pipeline around the tool activity:

| Phase | Interceptor | Priority | Effect |
|---|---|---|---|
| `pre_tool_call` | `CostBudgetGuard` | 100 | warn at 80% of run budget, deny when exhausted |
| `pre_tool_call` | `ServiceBudgetGuard` | 105 | warn at 80% of service budget, deny when exhausted |
| `pre_tool_call` | `SemanticGuard` | 400 | deny on `DROP TABLE`, `DROP DATABASE`, `rm -rf /`, `TRUNCATE TABLE`, disk format, shutdown; escalate on `DELETE FROM`, `UPDATE ... SET`, `ALTER TABLE`, `rm -rf`, `chmod 777` |
| `post_tool_call` | `OutputSanitizer` | 300 | rewrite matched content in the result |
| `tool_discovery` | `MCPToolSecurityScanner` | 300 | scan tool definitions returned by discovery |

These are pattern matchers over the tool arguments, not policy decisions. They
apply to every task regardless of what the effective policy says.

## What the policy decision actually does

All the enforcement points above call one function, `decide_tool_policy`, over the
resolved policy snapshot. It returns `ALLOW`, `DENY` or `REQUIRE_APPROVAL` in this
order:

1. If the tool name matches a `denied` pattern (glob), **deny**.
2. If an `allowed` allowlist is non-empty and the tool does not match it, **deny**.
3. If `requires_human_approval` is true, or the tool is listed in
   `escalation_rules`, **require approval**.
4. Otherwise **allow**.

Both keys in step 3 are read from the resolved policy snapshot. The identically
named `requires_human_approval` field on `TaskCreate` is a different thing at a
different layer and reaches no decision point — see
[approvals](/concepts/governance/approvals).

**This is default-allow, and that is deliberate.** The function is only ever asked
about a tool the agent is already composed with, so composition is the grant and
policy subtracts from it. An absent or empty allowlist means "no allowlist in
use", not "deny everything". Restriction is expressed by composing fewer tools or
by writing `deny` rules.

That posture is the single most important thing to understand about tool
authorization here, because it inverts the usual expectation. A workspace with no
policy rules does not deny tool calls; it allows every tool its agents are
equipped with.

## Why not put tool grants in the OpenFGA graph

An earlier design modelled tool invocation in the relationship graph: a `tool`
type with `can_call` and `callers` relations, a `session` type, per-session extra
grants, and an approval flag on the tool object. That design was reversed and the
graph types were removed.

The reason is that tool invocation is not a relationship question. It is a policy
question over composed candidacy, and the platform already has a policy engine
that resolves ceilings across four scopes with a proven monotonic merge. Putting
grants in the graph as well would create a second grant store beside it, with two
places to write an intent, two places to audit, and no defined precedence when
they disagree.

The tradeoff is that tool authorization gives up what the graph is good at. There
is no reverse lookup — you cannot ask the store "which users may call
`send_email`" — and there is no per-object scoping of a tool call, so
"may call `read_file` on this file but not that one" is not expressible. Argument
level authorization is not part of the decision at all: `decide_tool_policy`
receives the tool name and matches globs against it, and the tool arguments reach
only the pattern-matching gates.

## Limits

- **Default-allow, not deny-by-default.** Described above. Any statement anywhere
  that tool invocation is fail-closed and requires a graph grant describes a
  design that was reverted; the graph is not consulted on the tool path at all.
- **The decision is name-based.** Patterns are matched with `fnmatch` against the
  tool name. Two different MCP server instances exposing a tool with the same
  name are indistinguishable to policy — denying `create_issue` denies it
  everywhere.
- **The tool activity runs under a system context.** `execute_mcp_tool_activity`
  builds its database context from the workspace id only, without the invoking
  user. The policy verdict is computed with the user's snapshot, but the work
  downstream of it is not user-scoped. Anything that depends on the acting user's
  identity inside the tool execution path does not see it.
- **`SemanticGuard` escalation is a failure, not a pause.** Its medium-severity
  patterns return `ESCALATE`, which the Temporal bridge turns into an
  `EscalationRequired` exception. Because the interceptor sits at the activity
  boundary it cannot pause and wait for a human — the activity fails. Only the
  workflow-level approval path pauses.
- **The pattern gates are regular expressions.** `SemanticGuard`'s deny list
  covers a specific set of literal SQL and shell patterns. It is a guardrail
  against an obvious accident, not a defence against a model that is trying to get
  around it. Do not treat it as a sandbox boundary.
- **A crashing gate fails open.** The pipeline catches exceptions from an
  interceptor, logs the traceback and continues with the next one.
- **No rate or concurrency limit on tool calls.** Frequency is bounded only by the
  budget and iteration ceilings.

## Related

- [The policy engine](/concepts/governance/policy-engine) — how the snapshot the
  decision reads is built.
- [Approvals](/concepts/governance/approvals) — what `REQUIRE_APPROVAL` triggers,
  and on which paths.
- [Budgets and quotas](/concepts/governance/budgets-and-quotas) — the budget gates
  in the pipeline.
- [The AgentArea model](/concepts/governance/the-agentarea-model) — the graph,
  which governs the tool's *configuration* rather than its invocation.
