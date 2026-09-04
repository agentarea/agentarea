---
title: Require human approval for a tool
type: guide
summary: Make a tool call pause for a named approver, find the pending escalation, and resolve it — including why a successful-looking response can leave the task waiting.
prerequisites:
  - /concepts/governance/approvals
  - /guides/governance/authorize-a-tool-call
related:
  - /guides/governance/authorize-a-tool-call
  - /guides/governance/review-the-audit-trail
  - /concepts/governance/approvals
last_updated: 2026-07-29
---

# Require human approval for a tool

Do this when an agent may take an action but a person must sign it off first —
issuing a refund, deleting a record, sending mail to a customer. The workflow
stops before the call, records who may answer, and waits.

Do not do this for something the agent should never do; deny it instead, which
costs nothing at runtime. And do not use it on a path that cannot pause: a tool
called through the MCP proxy is refused rather than escalated, so approval only
works for tools invoked inside an agent task.

## Prerequisites

- You can create policy rules through `/v1/policies`.
- You know which user ids will approve. Name them; an empty approver list means
  anyone may resolve.
- Read [approvals](/concepts/governance/approvals) for what the pause can and
  cannot cover.

Examples assume `API=http://localhost:8000` and a bearer token in `$TOKEN`.

## Steps

There are two routes to the same enforcement. Both end as an agent-scoped
`APPROVAL` policy rule that the workflow gate reads.

| Route | Pick when |
|---|---|
| The agent's tool configuration | you are approving specific tools on one agent and want the agent editor to stay the source of truth |
| A policy rule written directly | you are approving across a whole workspace or a single user, or you need to name approvers |

### 1. Route A — tick the tool in the agent configuration

Set `requires_user_confirmation` on the tool inside the agent's `tools` config.
On save, `AgentService` reconciles the flags into agent-scoped rules: each ticked
tool becomes `PolicyRule(subject_type=agent, target="tool:<name>",
effect=approval)`, and unticking **deletes** the row rather than disabling it.
The flag is stripped before the tools JSON is stored and reconstituted from the
rules on read, so it has exactly one home.

The name in the rule is the LLM-facing one. A code toolset collapses its
namespace — `agentarea/shell` becomes `tool:shell` — while an MCP tool keeps the
raw name it advertises, which is its `allowed_tools` entry.

This route cannot name approvers. It produces a rule with no `approvers`
parameter, which means **anyone may approve**. If that is not acceptable, use
route B, or patch the generated rule's `params` afterwards.

### 2. Route B — write the rule directly

Everything below is this route. Choose per-tool or global.

**Per tool** is the usual choice. Target the tool by name and the approvers
attach to that tool alone:

```bash
curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_type": "agent",
        "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "target": "tool:refund_payment",
        "effect": "approval",
        "params": {"approvers": ["user:alice@example.com", "user:bob@example.com"]}
      }'
```

**Global** stops every capability tool call the agent makes. Reach for it only
when the agent is new or untrusted and you want a human in front of everything,
because it pauses on every single call:

```bash
curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_type": "agent",
        "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "target": "*",
        "effect": "approval",
        "params": {"approvers": ["user:alice@example.com"]}
      }'
```

`target: "tool:*"` behaves the same as `*` for this effect.

Approver references must be typed. `user:<id>` is the only form that grants
approval at resolution time. `group:<id>` and userset references such as
`team:eng#member` are validated and stored but match nobody — see
troubleshooting.

### 3. Confirm it merged

```bash
curl -s -X POST "$API/v1/governance/effective-policy/preview" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77"}' \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["effective_policy"]["approval"], indent=2))'
```

A per-tool rule shows up as an entry in `escalation_rules` plus a key in
`approvers_by_tool`. A global rule sets `requires_human_approval: true` and fills
the flat `approvers` list.

```json
{
  "requires_human_approval": null,
  "escalation_rules": ["refund_payment"],
  "approvers": [],
  "approvers_by_tool": {
    "refund_payment": ["user:alice@example.com", "user:bob@example.com"]
  }
}
```

### 4. Run a task and catch the escalation

Start a task that will reach the tool, then read the event stream for the pending
request. The escalation id is in the event data:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["events"]:
    if e["event_type"] == "approval.request":
        m = e["metadata"]
        print(m["escalation_id"], m["tool_name"], m["approvers"])'
```

You can also stream them live from
`GET /v1/agents/{agent_id}/tasks/{task_id}/events/stream`.

### 5. Resolve it

```bash
curl -s -X POST "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/resolve-escalation" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "escalation_id": "8b1f0c7e-2d44-4a91-b0c3-9e5f7a2d1c88",
        "approved": true,
        "comment": "Verified against ticket SUP-4412"
      }'
```

The approver is taken from the **authenticated caller**, not from the request
body — there is no `resolved_by` field to send, and none would be honoured. Call
this endpoint with the approver's own token.

Send `"approved": false` to deny. The comment is appended to the conversation as
a tool message so the model can react rather than retry blindly.

## Verify

**Before resolving**, the task reports the pause:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/status" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])'
```

```
waiting_for_approval
```

The `status` field is the persisted task's lifecycle state, which the workflow
updates when it pauses. `execution_status` in the same response is the live
Temporal view and still reads as running.

**After resolving**, an `approval.response` event carries the outcome and the
approver. Approve and deny share that one event type; the decision is in the
payload:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["events"]:
    if e["event_type"] == "approval.response":
        m = e["metadata"]
        print(m["tool_name"], "approved:", m["approved"], "by:", m.get("approved_by"))'
```

Once no escalations remain pending the task status returns to `running`.

## Troubleshooting

**The response said `resolved` but the task is still waiting.** This is the
failure that costs the most time. The endpoint returns
`{"status": "resolved", ...}` when the *signal was delivered*, not when the
approval was *accepted*. The workflow ignores a signal from a caller who is not
in the approver list, deliberately, so that the API boundary cannot bypass
policy. Check the worker log for:

```
Unauthorized escalation resolution for <id> by '<user>'; approvers=[...]. Ignored.
```

Resolve again as one of the named approvers.

**Anyone can approve.** An approval rule created without an `approvers` parameter
produces an empty list, and an empty list permits any caller. If the approval is
meant to mean something, name the approvers explicitly. Rules generated from the
agent configuration toggle (route A) always land in this state, because that
route has nowhere to express approvers.

**Unticking the toggle deleted my rule.** Working as designed. Route A treats the
agent configuration as the source of truth and reconciles to exactly the ticked
set: missing targets are created, unticked ones are deleted rather than
disabled. If you hand-edited a generated rule's `params` to add approvers,
unticking and re-ticking loses that edit.

**A hand-written rule and a toggle fight each other.** Reconciliation only
considers agent-scoped rules with effect `approval`, so a rule you wrote at that
same scope for a tool that is not ticked will be deleted on the next agent save.
Put hand-written approval rules at the workspace or user scope, or manage that
tool entirely through the toggle.

**Nobody can approve and the task hangs forever.** Approver matching resolves
only direct `user:<id>` subjects. A list containing solely `group:` or userset
references matches nobody, and because the list is non-empty the "anyone may
approve" default does not apply either. Replace them with explicit user
references.

**The task waits indefinitely.** There is no timeout, no auto-deny and no
escalation to a second approver. A task blocked on an approval nobody answers
stays in `waiting_for_approval` until you cancel it with
`DELETE /v1/agents/{agent_id}/tasks/{task_id}`.

**No notification arrived.** Core emits the `approval.request` event and updates
the task row; it does not send mail, post to a channel or page anyone. Consume
the event stream if you need to notify approvers.

**A proxied MCP call was refused instead of pausing.** Tool calls arriving at
`POST /v1/mcp/{instance_id}/mcp` are checked against the same decision, but
anything that is not a plain allow becomes HTTP 403 with no escalation created.
Approval only works for tools invoked inside an agent task.

**Setting `requires_human_approval` on the task did nothing.** `TaskCreate`
accepts a `requires_human_approval` boolean, and it is stored in the task's
metadata. It does not feed the approval policy and no enforcement point reads it.
Use an `approval` policy rule, or send an `approval` block inside `task_policy`.

**A destructive command was blocked rather than escalated.** A separate pattern
gate denies literal strings such as `DROP TABLE`, `rm -rf /` and `TRUNCATE
TABLE`, and marks `DELETE FROM`, `ALTER TABLE`, `rm -rf` and `chmod 777` for
escalation. That gate runs at the activity boundary, which cannot pause, so its
escalation fails the activity instead of creating an approval. It is a guardrail
against an accident, not part of this flow.

## Related

- [Approvals](/concepts/governance/approvals) — why the pause lives in the
  workflow and not in the interceptor pipeline.
- [Authorize a tool call](/guides/governance/authorize-a-tool-call) — deny, which
  is cheaper when the answer is always no.
- [Review the audit trail](/guides/governance/review-the-audit-trail) — where
  approval outcomes are, and are not, recorded.
