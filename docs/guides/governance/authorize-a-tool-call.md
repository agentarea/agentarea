---
title: Authorize a tool call
type: guide
summary: Allow or deny a specific tool for a workspace, agent or user, and work out which enforcement layer rejected a call that failed.
prerequisites:
  - /concepts/governance/tool-authorization
  - /concepts/governance/policy-engine
related:
  - /guides/governance/require-human-approval
  - /guides/governance/set-a-budget
  - /concepts/governance/tool-authorization
last_updated: 2026-07-29
---

# Authorize a tool call

Do this when an agent must not call a particular tool, or must be restricted to a
named set of tools. Do it as well when a tool call failed and you need to know
which of the several enforcement layers stopped it.

Do not do this to remove a tool from an agent entirely — that is composition, and
un-equipping the agent is cheaper than denying it. And do not expect a rule to
affect a task that is already running: the policy snapshot is frozen when the
task is created.

Start from the posture: **tool policy is default-allow.** An agent with no
matching rules may call every tool it is composed with. Restriction is something
you add.

## Prerequisites

- You can create policy rules through `/v1/policies`.
- You know the tool's name exactly. Matching is `fnmatch` glob against the name,
  and two MCP instances exposing the same tool name are indistinguishable.
- Read [tool authorization](/concepts/governance/tool-authorization) for the
  layers this guide manipulates.

Examples assume `API=http://localhost:8000` and a bearer token in `$TOKEN`.

## Steps

### 1. Choose the scope

A rule binds to one subject. The resolver merges the layers
workspace → agent → user → task, and a lower layer can only tighten.

| `subject_type` | `subject_id` | Pick when |
|---|---|---|
| `workspace` | the workspace id | the restriction applies to everything in the workspace |
| `agent` | the agent UUID | one agent must not use a tool other agents may |
| `user` | the user id | one person's tasks must be more restricted, whichever agent they run |
| `task` | — | not a rule; send `task_policy` on the task instead |

The `user` layer resolves from whoever created the task, which is how the same
agent produces different verdicts for different callers.

### 2. Choose deny or allowlist

**Deny a named tool** when the default set is right and one capability is not.
This is the option to reach for most of the time.

```bash
curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_type": "agent",
        "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "target": "tool:send_email",
        "effect": "deny"
      }'
```

**Use an allowlist** when the agent should be confined to a known set and you
want new tools to be excluded by default as they are added.

```bash
curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "subject_type": "agent",
        "subject_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77",
        "target": "tool:web_search",
        "effect": "allow"
      }'
```

Every `allow` rule at a layer contributes one entry to that layer's allowlist.
Once an allowlist is non-empty, anything outside it is denied. An absent or empty
allowlist means "no allowlist in use", not "deny everything".

Both effects require a **named** tool. `tool:*` is parsed as a valid target and
then skipped by the compiler, so a wildcard allow or deny rule is stored and does
nothing.

Response is HTTP 201 with the created rule, including its `id`.

### 3. Preview the merged result

Before running anything, resolve the layers without creating a task:

```bash
curl -s -X POST "$API/v1/governance/effective-policy/preview" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"agent_id": "3f9c1e42-7b5a-4f3e-9a10-2c8d6b4e1f77"}' \
  | python3 -c 'import json,sys; print(json.dumps(json.load(sys.stdin)["effective_policy"].get("tools"), indent=2))'
```

```json
{
  "allowed": null,
  "denied": ["send_email"]
}
```

The preview resolves the workspace, agent and calling user's layers. Pass
`task_policy` in the same body to see what a per-task document would do on top.

### 4. Tighten one task only

A per-task restriction rides on task creation rather than the rule table:

```bash
curl -s -X POST "$API/v1/agents/$AGENT_ID/tasks/" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
        "description": "Summarise the Q3 report",
        "task_policy": {"tools": {"denied": ["shell_exec"]}}
      }'
```

## Verify

**Check the snapshot the task actually carries.** This is the authoritative
answer, because it is what every enforcement point reads:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/governance/task-policy-snapshots/$TASK_ID" \
  | python3 -m json.tool
```

The response includes `source_policy_ids`, so you can confirm your rule is one of
the inputs, and `resolver_version` (`policy-resolver-v1`).

**Confirm the denial at runtime.** A denied call appears in the task event stream
as a `tool.result` event whose data carries `denied_by_policy: true`:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["events"]:
    if e["event_type"] == "tool.result" and e["metadata"].get("denied_by_policy"):
        print(e["metadata"]["tool_name"], "->", e["metadata"].get("error"))'
```

A denied tool is also **not offered to the model at all** — disclosure drops it
before the LLM call — so in a healthy configuration you should usually see the
agent never attempting it rather than attempting and being refused.

## Troubleshooting

**The rule exists and nothing changed.** Check the target kind. The compiler
handles `allow` and `deny` only on a named `tool:` target. Rules targeting
`mcp:<id>`, `model:<id>`, `skill:<id>`, `collection:<id>` or `tool:*` are
accepted by the API, stored, returned by `GET /v1/policies`, and then skipped
when the layer is compiled. They have no runtime effect. Confirm with the preview
endpoint: if `tools` is absent or unchanged, the rule did not compile.

**`422` when creating or previewing.** The resolver rejects a lower layer that
would loosen a higher one. An agent-level allowlist has to be a subset of the
workspace allowlist patterns; a task policy cannot re-enable a denied tool. The
error names the field that tried to widen.

**The task still calls the tool.** The snapshot is taken at task creation. A rule
written after the task started does not reach it, and there is no revocation path
into a running workflow. Cancel and restart the task.

**It works over the API but not through the MCP proxy, or the reverse.** The
proxy has no task snapshot, so it resolves only the workspace and calling user's
layers at request time. An **agent-scoped** rule therefore does not apply to a
proxy call. Move the rule to the workspace or user layer if it must cover both
paths.

**A tool the model should not see is still in its context.** Disclosure keeps
tools that require approval, and always keeps the control-flow tools
(`completion`, `task_complete`, `request_user_input`, `recall_history`,
`read_tool_output`, `activate_tool_source`, `load_tools`) regardless of policy, so
a restrictive rule cannot strand a run.

**The call failed but not with a policy reason.** Several other layers can stop a
tool call independently of your rules: the budget gates deny when the run or
service budget is exhausted, and a pattern gate denies destructive shell and SQL
strings such as `DROP TABLE`, `rm -rf /` or `TRUNCATE TABLE`. Those surface as an
activity failure rather than a `denied_by_policy` event. Read the worker log for
the interceptor name in the raised `GovernanceDenied`.

## Related

- [Tool authorization](/concepts/governance/tool-authorization) — every layer a
  call clears and why they are separate.
- [Require human approval](/guides/governance/require-human-approval) — the third
  verdict a tool decision can return.
- [Set a budget](/guides/governance/set-a-budget) — the other gates on the
  pre-tool phase.
