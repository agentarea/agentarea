---
title: Limits
type: reference
summary: Every ceiling, timeout, retry count and size bound on task execution and governance, with its persisted or deployment-owned source.
prerequisites: []
related:
  - /reference/policy-syntax
  - /reference/authorization-model
  - /reference/errors
  - /guides/governance/set-a-budget
last_updated: 2026-07-29
---

# Limits

The numeric bounds on task execution, governance and the authorization graph.
Every value below is the value in source; overrides are listed per limit.

## Synopsis

A limit comes from one of three places, and that decides how you change it.

| Source | Changed by | Scope |
|---|---|---|
| Policy rule | `POST /v1/policies`, or `task_policy` at task creation | Per workspace, agent, user or task, at runtime |
| Environment setting | Process environment or Helm values | Per deployment, at restart |
| Code constant | Editing the source and redeploying | Global |

## Fields

| Category | Source | Notes |
|---|---|---|
| Policy ceilings | Policy rule | Merge monotonically across four layers; a lower layer may only tighten. |
| Workflow and worker settings | Environment, prefix `WORKFLOW__` | `EXECUTION_ENGINE=temporal` makes the three `TEMPORAL_*` connection settings required with no defaults. |
| Access-control settings | Environment, prefix `ACCESS_CONTROL_` | See [Defaults and overrides](#defaults-and-overrides). |
| Agent-loop limits | Persisted effective policy | Required at task admission; runtime code has no numeric fallback. |
| Timeouts and retries | Environment or Temporal activity configuration | Per deployment. |
| Context and output sizes | Code constant | Not configurable. |
| Event-log bounds | Code constant | Apply to event projections only. |
| Pagination caps | Code constant | Clamped server-side. |

## Values

### Policy ceilings

| Limit | Default for a new workspace | Unit |
|---|---|---|
| `budget.monthly_spend_cap_usd` | `500.00` | USD per calendar month, UTC |
| `budget.run_budget_usd` | `50.00` | USD per task |
| `budget.service_budget_usd` | not seeded | USD per task |
| `tokens.max_tokens` | `20000000` | tokens per task |
| `tokens.max_tokens_per_call` | `100000` | maximum output tokens for one LLM call |
| `execution.max_model_turns` | `100` | model turns per task |
| `execution.max_tool_calls_per_turn` | `10` | tool calls per model turn |
| `execution.max_tool_calls_total` | `1000` | tool calls per task |

### Execution limits

The effective policy must contain run budget, total and per-call token ceilings,
model turns, per-turn tool calls, and total tool calls. Missing dimensions reject
task execution rather than selecting a code default. The values above are seed
data for a new workspace and become rows in the policy database; operators may
replace the seed file and existing workspace rules are not silently overwritten.

### Guard thresholds

Warning fires at the ratio; denial fires at full consumption.

| Guard | Warning threshold | Phase |
|---|---|---|
| `CostBudgetGuard` | 0.8 | pre-LLM and pre-tool |
| `ServiceBudgetGuard` | 0.8 | pre-tool |
| `TokenBudgetGuard` | 0.85 | pre-LLM |

### Timeouts

| Limit | Value |
|---|---|
| `ACTIVITY_TIMEOUT` | 5 minutes |
| `LLM_CALL_TIMEOUT` | 10 minutes |
| `TOOL_EXECUTION_TIMEOUT` | 35 minutes |
| `DELEGATION_TIMEOUT` | 10 minutes |
| `EVENT_PUBLISH_TIMEOUT` | 5 seconds |
| `HEARTBEAT_TIMEOUT` | 30 seconds |
| `CONTINUATION_TIMEOUT` | 24 hours |
| `WORKFLOW__AGENT_VALIDATION_TIMEOUT_MINUTES` | 5 |
| `WORKFLOW__AGENT_EXECUTION_TIMEOUT_HOURS` | 24 |
| `WORKFLOW__DYNAMIC_ACTIVITY_TIMEOUT_MINUTES` | 30 |
| `WORKFLOW__TEMPORAL_MAX_WORKFLOW_DURATION_DAYS` | 7 |
| `ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS` | 10.0 |

There is no timeout on a pending human approval.

### Retries

| Limit | Value |
|---|---|
| `DEFAULT_RETRY_ATTEMPTS` | 3 |
| `LLM_RETRY_ATTEMPTS` | 3 |
| `EVENT_PUBLISH_RETRY_ATTEMPTS` | 1 |

LLM calls retry transient failures with backoff. Permanent failures — auth,
quota, billing, an unknown model — fail fast via a non-retryable flag.

### Concurrency

| Limit | Value |
|---|---|
| `WORKFLOW__TEMPORAL_MAX_CONCURRENT_ACTIVITIES` | 10 |
| `WORKFLOW__TEMPORAL_MAX_CONCURRENT_WORKFLOWS` | 5 |

There is no per-workspace request rate limit, task concurrency quota, or tool
call rate limit.

### Context window management

| Limit | Value |
|---|---|
| `DEFAULT_CONTEXT_WINDOW` | 128000 tokens, when the model does not declare one |
| `CONTEXT_COMPACT_THRESHOLD` | 0.75 |
| `CONTEXT_WARNING_THRESHOLD` | 0.60 |
| `CONTEXT_RESERVE_FOR_OUTPUT` | 0.15 |
| `MIN_RECENT_MESSAGES_TO_KEEP` | 6 |
| `TOKENS_PER_MESSAGE_OVERHEAD` | 4 tokens |

### Output offloading

| Limit | Value |
|---|---|
| `TOOL_OUTPUT_OFFLOAD_CHARS` | 8000 characters |
| `OUTPUT_SUMMARY_HEAD_CHARS` | 500 |
| `OUTPUT_SUMMARY_TAIL_CHARS` | 200 |
| `READ_OUTPUT_MAX_RETURN_CHARS` | 16000 |
| `HISTORY_SEARCH_MAX_RESULTS` | 20 |

### Event-log bounds

Applied to Redis and database event projections. Activities and the model still
receive the original values.

| Limit | Value |
|---|---|
| Maximum string length kept inline | 2000 characters |
| Base64-like string omitted at | 256 characters |
| Control-character ratio treated as binary | above 0.02 |
| Maximum nesting depth | 10 |
| Maximum dictionary entries kept | 100 |
| Maximum list items kept | 100 |

Field names matching a secret pattern are replaced with `[redacted]`. Fields
carrying content, command text, stdout or stderr are replaced with a size marker.

### Pagination

| Endpoint area | Default | Maximum |
|---|---|---|
| Audit logs | 50 | 100, validated and clamped again server-side |
| OpenFGA bootstrap store and model listing | 100 per page | — |

## Enforcement

| Limit | Enforced at |
|---|---|
| `monthly_spend_cap_usd` | Task creation only. A running task is not interrupted, and the check has no lock, so concurrent creation can cross it. |
| `run_budget_usd` | The workflow loop, and `CostBudgetGuard` before each LLM and tool call. |
| `service_budget_usd` | The workflow loop, and `ServiceBudgetGuard` before each tool call. |
| `max_tokens` | `TokenBudgetGuard` before each LLM call. |
| `max_tokens_per_call` | LLM call resolution; the strictest of policy, request, and model capability wins. |
| `execution.max_model_turns`, `execution.max_tool_calls_per_turn`, `execution.max_tool_calls_total` | The workflow loop and tool-call budget. |
| Timeouts and retries | Temporal activity options. |
| Event-log bounds | Event projection, before publish and persist. |

| Condition | Behaviour |
|---|---|
| A budget ceiling absent or not greater than zero | The guard allows unconditionally. `null` is not zero. |
| A required runtime policy dimension is missing | Task execution fails closed with the missing field named. |
| A service budget of zero or less | Treated as unlimited. |
| A guard raising an exception | Logged with a traceback; the pipeline continues. Fail-open for that dimension. |
| Month-to-date spend | Summed from persisted task cost from the first of the current UTC month. Spend from a task still running is not fully counted. |
| Per-call cost | Read from the provider response where supplied; otherwise estimated at a flat rate per token. |

The `max_depth` parameter on the graph client's check accepts a value and
defaults to 10, but it is not sent in the request. Setting it has no effect.

## Defaults and overrides

Where a default exists in more than one place, the code default is authoritative
for a process started without the corresponding environment variable.

| Setting | Code default | `docker-compose.dev.yaml` | `docker-compose.yaml` | Helm |
|---|---|---|---|---|
| `ACCESS_CONTROL_BACKEND` | `disabled` | `openfga` | **absent — code default applies** | `openfga` when `openfga.enabled=true`, the chart default |
| `ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP` | `false` | `true` | absent | `true` |
| `ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL` | `false` | `true` | absent | `true` |
| `ACCESS_CONTROL_OPENFGA_STORE_NAME` | `agentarea` | `agentarea` | absent | — |
| `ACCESS_CONTROL_OPENFGA_API_URL` | `http://openfga:8080` | `http://openfga:8080` | absent | — |

`make up` runs `docker-compose.yaml` and `make up-dev` runs
`docker-compose.dev.yaml`. On the `make up` path the graph backend is `disabled`,
in which case every permission check returns allow.

| Setting | Code default | Override |
|---|---|---|
| `GOVERNANCE_DEFAULT_POLICIES_PATH` | unset, uses the packaged `config/default_policies.yaml` | Path to an alternative defaults file. A missing file means new workspaces start with no rules. |
| `WORKFLOW__EXECUTION_ENGINE` | `temporal` | `direct` ignores the `TEMPORAL_*` settings. |
| `WORKFLOW__TEMPORAL_SERVER_URL` | `""` | Required when the engine is `temporal`; startup validation fails if missing. |
| `WORKFLOW__TEMPORAL_NAMESPACE` | `""` | Required when the engine is `temporal`. |
| `WORKFLOW__TEMPORAL_TASK_QUEUE` | `""` | Required when the engine is `temporal`. |

Every constant listed under [Values](#values) that is not shown with an
environment prefix is a code constant with no override.

## Example

Tighten one task below the workspace ceiling. The effective run budget becomes
the minimum of the request value and every layer above it:

```json
{
  "description": "Summarise the Q3 report",
  "task_policy": {"budget": {"run_budget_usd": "2.50"}}
}
```

## See also

- [Policy rule syntax](/reference/policy-syntax) — how to write the ceilings.
- [Authorization model](/reference/authorization-model) — the access-control
  settings in full.
- [Errors](/reference/errors) — what exceeding a limit returns.
- [Budgets and quotas](/concepts/governance/budgets-and-quotas) — why the
  monthly cap is admission-only.
