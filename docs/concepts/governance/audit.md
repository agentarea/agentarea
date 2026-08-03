---
title: Audit
type: concept
summary: The two separate trails AgentArea keeps — the append-only audit log for control-plane changes and the task event stream for what a run did — and what neither of them records.
prerequisites: []
related:
  - /concepts/governance/policy-engine
  - /concepts/governance/the-agentarea-model
  - /concepts/governance/approvals
last_updated: 2026-07-29
---

# Audit

AgentArea keeps two trails, and they answer different questions. The **audit log**
records control-plane changes: who created an agent, who edited a policy rule, who
deleted an MCP server. The **task event stream** records what a run did: which
tools it called, which were denied, which paused for approval, how it ended.

They are separate stores with separate retention, separate APIs and separate
coverage. Treating either as "the audit trail" will leave a gap.

## The problem

Two questions look similar and are not.

"Who changed this configuration, from where, and what did it look like before?"
is a compliance question. It needs an actor, a timestamp, a source address, a
field-level diff, and a store that cannot be edited after the fact.

"What did this agent actually do on Tuesday?" is an execution question. It needs a
high-volume ordered stream of everything a run did, correlated to a task, and it
needs to be cheap enough to write on every tool call.

A single store optimised for one is bad at the other. Field-level diffs on every
tool call would be enormous; an append-only compliance store fed by a model loop
would swamp the queries that matter.

## The audit log

`audit_events` is a workspace-scoped, append-only table. Each row carries:

| Group | Fields |
|---|---|
| Who | `actor_id`, `actor_type` (`user`, `service`, `system`, `api_key`) |
| Where | `workspace_id`, `source_ip`, `user_agent`, `request_id` |
| What | `action` (hierarchical, for example `agent.create`), `resource_type`, `resource_id` |
| Change | `changes` — a list of `{field, before, after}` for mutations |
| Context | `event_metadata` |

Four composite indexes cover the queries that get asked: by workspace and time, by
actor, by resource, and by action.

Rows are written by an `@audited` decorator on service methods. For a create the
resource id comes from the return value; for an update or delete the decorator
snapshots the resource before the call and computes a field-level diff against the
result, skipping `created_at` and `updated_at`. Request context — source IP from
`X-Forwarded-For` or the direct client, user agent, and the `X-Request-ID` header
or a generated UUID — is captured by a FastAPI middleware into context variables
that the audit service reads.

The actions covered today are agent create, update and delete; skill create,
update and delete; MCP server create, update and delete; MCP instance create,
update and delete; trigger create, update and delete; task create; and governance
policy create, update, set-enabled and delete.

Reads go through `GET /v1/audit-logs/`, scoped to the caller's workspace and
filterable by action, actor, resource type, resource id and a time range. It is
cursor-paginated with a default of 50 and a maximum of 100 events per page,
newest first.

Enterprise deployments can register an `audit_sink` extension; when present, every
recorded event is also forwarded to it for SIEM or object-storage delivery. A
forwarding failure is logged and does not fail the write.

## The task event stream

Everything a run does is published as events: `llm.call.started` and
`llm.call.completed`, `tool.call` and `tool.result`, delegations, budget warnings,
`approval.request` and `approval.response`, and the terminal states. Events are
published to Redis for live streaming and persisted for history, which is what
lets a client attach after a task finishes and still render the outcome.

This is where governance outcomes at runtime show up. A tool call denied by policy
emits `tool.result` carrying `denied_by_policy: true` and the denial reason. An
approval emits the request and the response, the latter including the approver's
user id and the decision.

Event payloads are sanitized before they are written. Fields whose names suggest
secrets are redacted; fields carrying file bodies, command text, stdout or stderr
are replaced with a size marker; strings over 2,000 characters, base64-looking
blobs and binary content are omitted. The activity and the model still receive the
original values — only the event projection is bounded.

## Why not one unified trail

Merging the two would fail on volume and on integrity at the same time.

An agent run produces events at model speed: several per iteration, dozens per
task, and the payloads include tool arguments and results. Writing those into a
table designed to be append-only, indexed four ways, and retained for compliance
makes the compliance queries slow and the storage cost dominated by the noisiest
data. Conversely, giving the event stream the guarantees the audit log needs —
immutability, a diff per change, an actor resolved from the request — would make
every tool call pay for machinery it does not use.

The cost of keeping them separate is exactly what you would expect: two stores to
query, two retention decisions to make, and a correlation step when an
investigation crosses the boundary. A control-plane change and the run it affected
are joined by workspace and timestamp, not by a shared identifier.

## Limits

- **Runtime governance decisions do not reach the audit log.** The governance
  pipeline registers an `AuditObserver` on every phase, but it is constructed
  without an event sink, so it logs at debug level and returns. No tool call, no
  policy denial, no budget denial and no approval produces an `audit_events` row.
  Those live only in the task event stream and in application logs.
- **Authorization grant changes are not audited.** Writing or revoking a
  relationship through `/v1/access-control/relationships`, and the automatic owner
  grants written when a resource is created, produce no audit event. Who was given
  access to what is recorded in the graph itself, not in the audit log.
- **API key lifecycle is not audited.** Creating and deleting API keys produces no
  audit event.
- **A failed audit write does not fail the action.** The decorator wraps the
  recording step in a try/except that logs a warning. If the audit insert fails,
  the mutation still succeeds and the event is lost.
- **Audit is skipped silently when the shape does not match.** The decorator needs
  a `repository_factory` on the service; without one it calls straight through and
  records nothing. The before-state snapshot additionally needs a `repository`
  attribute and a `to_dict` method, and falls back to no diff when either is
  missing.
- **`actor_type` is effectively always `user`.** The service defaults it and no
  decorated call site overrides it, so an action taken with an API key is recorded
  with the resolved user id and the type `user`. The distinction the column exists
  for is not populated.
- **Append-only is a deployment instruction, not a code guarantee.** The
  repository only inserts and reads, and the model documents that only INSERT and
  SELECT should be granted on the table. Nothing in the application enforces that;
  a role with UPDATE or DELETE can rewrite history.
- **There is no retention or archival in core.** No expiry job, no configurable
  retention window, no export beyond the enterprise sink extension. Both stores
  grow until you manage them.
- **Reads are workspace-scoped and otherwise unrestricted.** Any authenticated
  member of a workspace can read that workspace's full audit log through the API.

## Related

- [The policy engine](/concepts/governance/policy-engine) — the policy mutations
  that do produce audit events.
- [Approvals](/concepts/governance/approvals) — where approval outcomes are
  recorded.
- [The AgentArea model](/concepts/governance/the-agentarea-model) — the grant
  changes that are not.
