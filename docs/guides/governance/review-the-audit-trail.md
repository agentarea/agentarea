---
title: Review the audit trail
type: guide
summary: Query the audit log for control-plane changes, page through results, read field-level diffs, and know which trail to use when the audit log has no answer.
prerequisites: []
related:
  - /concepts/governance/audit
  - /guides/governance/grant-resource-access
  - /guides/governance/require-human-approval
last_updated: 2026-07-29
---

# Review the audit trail

Do this to answer "who changed this, when, and from where" about configuration:
agents, skills, MCP servers, triggers, tasks and policy rules. The audit log
records the change, the actor, the request context and a field-level diff.

Do not use it to reconstruct what an agent did while running. Tool calls,
denials, budget warnings and approvals are in the task event stream, not in the
audit log — the two are separate stores. If your question is about a run, skip to
[the second trail](#when-the-audit-log-has-no-answer).

## Prerequisites

- An authenticated session in the workspace you want to inspect. Reads are
  workspace-scoped, and any authenticated member can read their workspace's full
  audit log.
- Read [audit](/concepts/governance/audit) for what each trail covers.

Examples assume `API=http://localhost:8000` and a bearer token in `$TOKEN`.

## Steps

### 1. Read the most recent events

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$API/v1/audit-logs/" \
  | python3 -c '
import json,sys
d = json.load(sys.stdin)
for e in d["events"]:
    print(f"{e[\"created_at\"]}  {e[\"action\"]:28} {e[\"resource_type\"]}/{e[\"resource_id\"]}  by {e[\"actor_id\"]}")
print("next_cursor:", d["next_cursor"])'
```

Events come back newest first. The default page is 50 and the maximum is 100.

### 2. Narrow with filters

All filters combine, and all are optional.

| Query parameter | Example | Use when |
|---|---|---|
| `action` | `agent.delete` | you know exactly what happened |
| `actor_id` | a user id | you are investigating one person's activity |
| `resource_type` | `agent`, `skill`, `mcp_server`, `mcp_instance`, `trigger`, `task`, `governance_policy` | you want everything that happened to one kind of object |
| `resource_id` | a UUID | you want the history of one specific object |
| `since` / `until` | ISO 8601 | you are bounding an incident window |
| `limit` | 1 to 100 | you are paging |

```bash
curl -s -G -H "Authorization: Bearer $TOKEN" "$API/v1/audit-logs/" \
  --data-urlencode "resource_type=agent" \
  --data-urlencode "resource_id=$AGENT_ID" \
  --data-urlencode "since=2026-07-01T00:00:00Z" \
  | python3 -m json.tool
```

The action names are hierarchical and follow `<resource>.<verb>`. The set written
today is agent, skill, mcp_server, mcp_instance and trigger create/update/delete,
`task.create`, and `governance_policy.create`, `.update`, `.set_enabled` and
`.delete`.

### 3. Page through a long window

Pass the previous response's `next_cursor` as `cursor`:

```bash
CURSOR=$(curl -s -H "Authorization: Bearer $TOKEN" "$API/v1/audit-logs/?limit=100" \
         | python3 -c 'import json,sys; print(json.load(sys.stdin)["next_cursor"] or "")')

curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/audit-logs/?limit=100&cursor=$CURSOR" | python3 -m json.tool
```

The cursor is the id of the last event on the previous page; the next page
returns events strictly older than it.

### 4. Read what actually changed

Update and delete events carry a `changes` array of `{field, before, after}`:

```bash
curl -s -G -H "Authorization: Bearer $TOKEN" "$API/v1/audit-logs/" \
  --data-urlencode "action=agent.update" \
  | python3 -c '
import json,sys
for e in json.load(sys.stdin)["events"]:
    print(e["created_at"], e["resource_id"], "from", e["source_ip"], "req", e["request_id"])
    for c in e["changes"] or []:
        print(f"   {c[\"field\"]}: {c[\"before\"]!r} -> {c[\"after\"]!r}")'
```

`created_at` and `updated_at` are excluded from diffs. Create events have no
diff, because there is no before-state.

`source_ip` comes from `X-Forwarded-For` when present and the direct client
otherwise, so it is only as trustworthy as your proxy configuration.
`request_id` is the inbound `X-Request-ID` header, or a generated UUID when the
caller did not send one — send your own to correlate with upstream logs.

## Verify

Make a change you can predict, then find it:

```bash
RULE_ID=$(curl -s -X POST "$API/v1/policies" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"subject_type":"workspace","subject_id":"'"$WORKSPACE_ID"'","target":"tool:send_email","effect":"deny"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -s -G -H "Authorization: Bearer $TOKEN" "$API/v1/audit-logs/" \
  --data-urlencode "action=governance_policy.create" --data-urlencode "limit=1" \
  | python3 -m json.tool
```

The top event should be `governance_policy.create` with your user id as
`actor_id`, timestamped within seconds of the call.

## When the audit log has no answer

Several things are deliberately or accidentally absent. Knowing which is which
saves an investigation.

**Runtime governance decisions are not there.** No tool call, policy denial,
budget denial or approval produces an audit row. The pipeline's audit observer is
registered but constructed without an event sink, so it logs at debug level and
writes nothing. Use the task event stream instead:

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$API/v1/agents/$AGENT_ID/tasks/$TASK_ID/events" | python3 -m json.tool
```

That stream carries `tool.call`, `tool.result` (including `denied_by_policy`),
`llm.call.*`, `approval.request`, `approval.response`, `BudgetWarning`,
`BudgetExceeded` and the terminal states.

**Authorization grant changes are not there.** Writing or revoking a relationship
through `/v1/access-control/relationships`, and the owner grants written
automatically when a resource is created, produce no audit event. Who has access
is recorded in the graph itself — read it with
`GET /v1/access-control/relationships` and `POST /v1/access-control/resolve`.

**API key lifecycle is not there.** Creating and deleting keys under
`/v1/api-keys/` writes no audit event.

## Troubleshooting

**An action you expected is missing.** Check it is one of the covered actions
above. Beyond coverage, two mechanics drop events silently: the decorator skips
auditing when the service has no repository factory, and it catches and logs
failures from the audit write so the mutation still succeeds. A warning in the
API log reading `Failed to record audit event for <action>` is the signal.

**`actor_type` says `user` for an API-key call.** The column exists to
distinguish `user`, `service`, `system` and `api_key`, but no call site sets it,
so everything is recorded as `user` with the resolved user id. You cannot tell
interactive from programmatic activity from this field. Use `user_agent` and
`source_ip` as a weaker proxy.

**`limit=500` returned 100 rows.** The parameter is validated to 1-100 and the
repository clamps it again. Page with `cursor`.

**Events stop at a certain date.** There is no retention or archival job in core,
so this is not expiry — check whether the workspace filter is what you expect.
Reads are scoped to the caller's current workspace, and switching workspaces
changes the result set entirely.

**You need the log somewhere else.** Core has no export endpoint. Enterprise
deployments can register an `audit_sink` extension that receives every recorded
event for SIEM or object-storage delivery; a forwarding failure is logged and
does not fail the write.

**You are relying on immutability.** The repository only inserts and reads, and
the table is documented as append-only, but nothing in the application enforces
that. Grant only INSERT and SELECT on `audit_events` at the database level if the
guarantee matters.

## Related

- [Audit](/concepts/governance/audit) — the two trails and why they are separate.
- [Grant access to a resource](/guides/governance/grant-resource-access) — grant
  changes, which this log does not record.
- [Require human approval](/guides/governance/require-human-approval) — approval
  outcomes, which live in the event stream.
