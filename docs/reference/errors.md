---
title: Errors
type: reference
summary: The problem+json envelope every API error uses, the machine-readable codes, the governance and authorization responses in detail, and the responses that succeed without doing anything.
prerequisites: []
related:
  - /reference/policy-syntax
  - /reference/authorization-model
  - /reference/limits
  - /guides/governance/authorize-a-tool-call
last_updated: 2026-07-29
---

# Errors

Every API error is an RFC 9457 problem-detail document with media type
`application/problem+json`. A registered catch-all guarantees no response body is
plain text, including unhandled exceptions.

## Synopsis

```json
{
  "type": "about:blank",
  "title": "Payment Required",
  "status": 402,
  "code": "budget_cap_exceeded",
  "detail": "workspace 1c2f0a9b has spent 251.40 of its 250.00 monthly cap",
  "current_mtd_usd": 251.4,
  "cap_usd": 250.0,
  "workspace_id": "1c2f0a9b-4d6e-4b71-9f30-8a5c7d1e2b44"
}
```

## Fields

| Name | Type | Default | Description |
|---|---|---|---|
| `type` | string (URI) | `about:blank` | Problem type identifier. |
| `title` | string | the HTTP status phrase | Short, human-readable summary. Falls back to `"Error"` when the status code is not a known phrase. |
| `status` | integer | required | The HTTP status code, duplicated in the body. |
| `code` | string | required | Machine-readable identifier. Branch on this, not on `detail`. |
| `detail` | string | required | Human-readable, client-safe message. Never empty — falls back to `title`, then the status phrase. |
| *extensions* | any | — | Extra keys merged at the top level. They never overwrite a standard member. |

Known extensions:

| Extension | Appears with | Type |
|---|---|---|
| `errors` | `validation_error` | array of field-level validation errors |
| `current_mtd_usd` | `budget_cap_exceeded` | number |
| `cap_usd` | `budget_cap_exceeded` | number |
| `workspace_id` | `budget_cap_exceeded` | string |

## Values

### Codes

| Code | Status | Meaning | Action |
|---|---|---|---|
| `bad_request` | 400 | Malformed request the schema did not catch. | Correct the request. |
| `missing_context` | 400 | No workspace context could be resolved for the caller. | Authenticate, and send a workspace the caller can access. |
| `authentication_failed` | 401 | No credential, or one that did not verify. A `WWW-Authenticate` header accompanies the response. | Obtain a valid token or API key. |
| `budget_cap_exceeded` | 402 | Workspace month-to-date spend has reached its policy cap. | Raise the cap, wait for the next calendar month, or reduce spend. Read `current_mtd_usd` and `cap_usd`. |
| `permission_denied` | 403 | The permission service or the write-protection layer denied the action. | Obtain the missing grant. See [authorization model](/reference/authorization-model). |
| `not_found` | 404 | The resource does not exist in the caller's workspace. Also returned for cross-workspace ids. | Confirm the id and the active workspace. |
| `conflict` | 409 | Unique or foreign-key violation (SQLSTATE `23505` or `23503`). | Resolve the duplicate or the missing reference. |
| `validation_error` | 422 | Request body or query failed schema validation. Field detail is in `errors`. | Fix the named fields. |
| `http_error` | any | An `HTTPException` raised in route code. The status carries the meaning; `code` does not. | Read `detail` and `status`. |
| `workspace_error` | 500 | Workspace resolution failed internally. | Retry; escalate if persistent. |
| `internal_error` | 500 | Unhandled exception, or an integrity error that is not a conflict. Logged with a traceback. | Retry; report with the `request_id` you sent. |

`http_error` is the code you will see most often from the governance and
authorization endpoints, because they raise `HTTPException` directly. Branch on
`status` plus `detail` for those, and treat `code` as uninformative.

### Governance and authorization responses

| Status | `detail` | Raised by |
|---|---|---|
| 403 | `Permission denied` | `require_permission`, when the graph check returns false or the verb is unmapped |
| 403 | `Only a workspace admin may modify the authorization graph` | every `/v1/access-control` endpoint |
| 403 | `<Namespace>:<id> not found in your workspace` | object workspace assertion |
| 403 | `Subject user is not in your workspace` | subject workspace assertion |
| 403 | `Tool call denied: <tool>: <reason>` | MCP proxy tool authorization |
| 404 | `Policy rule not found` | policy rule read, update, delete |
| 404 | `Task policy snapshot not found` | snapshot read, when the task or its workflow is absent |
| 404 | `Agent not found` | escalation resolution |
| 422 | `Unsupported namespace: '<value>'` | namespace outside the accepted set |
| 422 | `Invalid object id: '<value>'` | object id is not a UUID |
| 422 | `Unsupported subject: '<value>'` | subject is neither `User:` nor `Agent:` |
| 422 | `Unsupported relation for a resource grant: '<value>'` | relation outside the accepted aliases |
| 422 | `Group (subject_set) grants are managed via project/role, not the explorer` | a `subject_set` body |
| 422 | `subject_id is required` | neither `subject_id` nor `subject_set` supplied |
| 422 | a policy validation message naming the field | a lower policy layer that would loosen a higher one |
| 500 | `Failed to resolve escalation` | escalation signal could not be delivered |
| 503 | `Graph authorization is disabled` | a graph write with no backend configured |
| 503 | `Graph authorization write failed` / `delete failed` / `check failed` | backend reachable but the operation failed |
| 503 | `<Backend> grant writer is unavailable` | backend enabled but no client registered in the container |
| 503 | `<Backend> grant write failed` | owner-grant write on resource creation |

### Tool authorization decision reasons

Returned in a denial `detail`, and in the tool result of a denied in-task call.

| Reason | Cause |
|---|---|
| `tool '<name>' is denied by policy` | matched a `denied` pattern |
| `tool '<name>' is not permitted by the policy allowlist` | a non-empty allowlist that the name falls outside |
| `tool '<name>' requires approval` | approval required — a denial only outside the agent workflow |

## Enforcement

Three responses report success without the effect the caller expects. None is a
transport error, so none is retryable.

| Response | What actually happened | How to confirm |
|---|---|---|
| `200 {"status": "resolved", ...}` from escalation resolution | The signal was delivered. If the caller is not in the approver list the workflow ignores it and the task stays paused. | Task status stays `waiting_for_approval`. Worker log: `Unauthorized escalation resolution for <id> by '<user>'; approvers=[...]. Ignored.` |
| `201` from policy rule creation | The row exists. If the effect and target combination is not one the compiler handles, it never reaches the runtime. | Resolve the effective policy and check the dimension changed. See [policy rule syntax](/reference/policy-syntax#enforcement). |
| `200 {"allowed": false}` from a permission check | Either a genuine denial, or a relation that is neither a mapped verb nor a permission bit, which short-circuits before the graph is queried. | Send a mapped verb or a bit name. |

A denial inside a task run is not an HTTP error. It appears as a `tool.result`
event carrying `denied_by_policy: true` and the reason.

## Defaults and overrides

Failure posture per component. None of these is configurable.

| Component | On backend failure |
|---|---|
| Permission service (OpenFGA) | Raises. The check does not coerce to allow or deny; the caller surfaces the failure. |
| Permission service (backend `disabled`) | Returns allow for every check. |
| Graph write on resource creation | HTTP 503. The create does not proceed. |
| Graph read endpoints with no backend | `enabled: false` with an empty result, HTTP 200. |
| Interceptor gate raising | Logged with a traceback; the pipeline continues to the next interceptor. Fail-open for that dimension. |
| Audit event write failing | Logged at warning level; the audited mutation still succeeds. |
| Enterprise audit sink failing | Logged at warning level; the database write still succeeds. |
| Integrity error, SQLSTATE `23505` or `23503` | 409 `conflict`. |
| Integrity error, any other SQLSTATE | 500 `internal_error` with a traceback, treated as a bug. |

## Example

A lower policy layer attempting to raise a ceiling:

```json
{
  "type": "about:blank",
  "title": "Unprocessable Entity",
  "status": 422,
  "code": "http_error",
  "detail": "run_budget_usd cannot loosen higher-scope ceiling"
}
```

## See also

- [Policy rule syntax](/reference/policy-syntax) — which rules validate and which
  silently do nothing.
- [Authorization model](/reference/authorization-model) — what a 403 from a
  permission check means.
- [Limits](/reference/limits) — the timeouts whose expiry produces a 5xx.
