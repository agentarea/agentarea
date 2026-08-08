---
title: Set a budget
type: guide
summary: Cap monthly spend, per-run spend, service spend or tokens for a workspace, agent, user or single task, and confirm the ceiling reached the run.
prerequisites:
  - /concepts/governance/budgets-and-quotas
related:
  - /guides/governance/authorize-a-tool-call
  - /guides/governance/review-the-audit-trail
  - /concepts/governance/policy-engine
last_updated: 2026-07-29
---

# Set a budget

Do this to bound what an agent can spend before it spends it. There are four
ceilings — monthly spend, per-run spend, service spend and tokens — and they are
enforced in different places, so choosing the right one matters more than the
number.

Do not use a budget to stop an agent doing something specific; that is a
[tool rule](/guides/governance/authorize-a-tool-call). And do not expect a
tightened budget to interrupt a task that is already running.

New workspaces are seeded with a baseline: 500.00 USD per month, 50.00 USD per
run, 20,000,000 tokens total and 100,000 tokens per call. You are usually
adjusting those rather than creating them from nothing.

## Prerequisites

- You can create policy rules through `/v1/policies`.
- Read [budgets and quotas](/concepts/governance/budgets-and-quotas), in
  particular which ceiling is admission-only.

Examples assume `API=http://localhost:8000` and a bearer token in `$TOKEN`.

## Steps

### 1. Choose the ceiling

| Ceiling | Target and params | Enforced | Pick when |
|---|---|---|---|
| Monthly spend | `spend`, `{"amount_usd": "...", "period": "month"}` | task creation | you need a hard stop on workspace spend per calendar month |
| Per-run spend | `spend`, `{"amount_usd": "...", "period": "run"}` | inside the loop and before each LLM and tool call | you need to bound one runaway task |
| Service spend | `service`, `{"amount_usd": "..."}` | before each tool call | the agent makes paid calls on your behalf |
| Tokens | `tokens`, `{"max_tokens": N}` | before each LLM call | you bound by context rather than cost |

Amounts are accepted as a string or a number; use a decimal string such as
`"250.00"` to avoid float rounding. They come back as strings.

### 2. Create the cap

```bash
curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_type": "workspace",
        "subject_id": "'"$WORKSPACE_ID"'",
        "target": "spend",
        "effect": "cap",
        "params": {"amount_usd": "250.00", "period": "month"}
      }'
```

Scope it more tightly by changing the subject. `subject_type: "agent"` with the
agent UUID bounds one agent; `subject_type: "user"` with a user id bounds
whatever that person launches. Lower scopes may only lower the number.

### 3. Adjust an existing cap instead of stacking one

The workspace baseline already contains a monthly and a per-run cap. Find the row
and patch it rather than adding a second:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/policies?subject_type=workspace&subject_id=$WORKSPACE_ID&effect=cap" \
  | python3 -c '
import json,sys
for r in json.load(sys.stdin):
    print(r["id"], r["target"], r["params"])'
```

```bash
curl -s -X PATCH "$API/v1/policies/$RULE_ID" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"params": {"amount_usd": "100.00", "period": "month"}}'
```

`PATCH` replaces `params` wholesale, so include `period` even when only the
amount changes. To switch a cap off without deleting it, send
`{"enabled": false}` — disabled rules are skipped when the layer compiles.

### 4. Bound a single task

A per-task ceiling rides on task creation:

```bash
curl -s -X POST "$API/v1/agents/$AGENT_ID/tasks/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "description": "Summarise the Q3 report",
        "task_policy": {"budget": {"run_budget_usd": "2.50"}}
      }'
```

This can only tighten. A task asking for more than the agent or workspace allows
is rejected.

## Verify

**Preview the merged ceiling** before running anything:

```bash
curl -s -X POST "$API/v1/governance/effective-policy/preview" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id": "'"$AGENT_ID"'"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin)["effective_policy"]; print(json.dumps({"budget": d.get("budget"), "tokens": d.get("tokens")}, indent=2))'
```

```json
{
  "budget": {
    "monthly_spend_cap_usd": "100.00",
    "run_budget_usd": "50.00",
    "service_budget_usd": null
  },
  "tokens": {
    "max_tokens": 20000000,
    "max_tokens_per_call": 100000
  }
}
```

**Confirm the snapshot a task carries:**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/governance/task-policy-snapshots/$TASK_ID" \
  | python3 -m json.tool
```

**Confirm the monthly cap bites.** Once month-to-date spend reaches the cap, task
creation returns HTTP 402 with a problem document naming the numbers:

```json
{
  "code": "budget_cap_exceeded",
  "current_mtd_usd": 251.4,
  "cap_usd": 250.0,
  "workspace_id": "..."
}
```

**Confirm the run budget bites.** The loop emits `BudgetWarning` at 80 percent
and `BudgetExceeded` when it stops:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["events"]:
    if e["event_type"] in ("BudgetWarning", "BudgetExceeded", "ServiceBudgetWarning", "ServiceBudgetExceeded"):
        print(e["event_type"], e["message"])'
```

## Troubleshooting

**`422` when creating the rule or previewing.** A lower scope tried to raise a
higher one's ceiling. Budgets merge by taking the minimum, and the resolver
rejects rather than silently clamping so the mistake is visible. Raise the parent
first, or lower the child.

**The cap was set and the task still overspent.** The monthly cap is admission
control only. A task that starts under the cap runs to completion no matter how
far past the cap the workspace goes, and the check is a read-then-decide with no
lock, so concurrent task creation can cross it. For a hard per-task bound use the
run budget, which is enforced inside the loop and before each call.

**Month-to-date looks wrong.** It is summed from `total_cost` on the workspace's
task rows from the first of the current UTC month. Spend from a task still in
flight is not fully counted until it finishes, so the figure trails reality while
work is running.

**A task is rejected because a ceiling is missing.** Runtime execution requires
an explicit run budget, total and per-call token ceilings, and agent-loop limits
in the resolved governance snapshot. Deleting the persisted workspace defaults
does not reveal a built-in numeric fallback; it makes the runtime contract
invalid. Restore the missing policy rows and re-check the preview output.

**`max_tokens_per_call` appears lower than expected.** It is enforced on every
LLM call. The resolver takes the strictest positive value from the effective
policy, the request, and the model's declared output capability, so inspect all
three sources before changing the workspace rule.

**The numbers do not match between the loop and the per-call gate.** They are two
enforcement points reading one resolved ceiling — the tighter of the per-request
budget and the policy value. If they disagree, the request carried its own
`budget_usd`; the minimum wins, so check what the caller sent.

**A budget denial appears as a failed activity, not a graceful stop.** The
per-call gate raises rather than returning a message the model can answer. The
graceful path — the loop noticing exhaustion and completing — comes from the
in-workflow tracker. Both are expected; which you see depends on where the
ceiling was crossed.

## Related

- [Budgets and quotas](/concepts/governance/budgets-and-quotas) — the enforcement
  points and their thresholds.
- [The policy engine](/concepts/governance/policy-engine) — how ceilings merge
  across scopes.
- [Authorize a tool call](/guides/governance/authorize-a-tool-call) — the other
  restriction you write as a policy rule.
