# Activities of the Go run

The whole run is Go: workflows and activities, on Go task queues. Python is
read only as the specification of behaviour; nothing in Go calls Python or is
called by it, no Python history is replayed, and the payloads are Go types
designed for the Go workflows (`payloads.go`, `../api/runconfig.go`). Each
`workflow.patched` branch of the Python workflow is ported as its newest
branch only.

Paths below: `EX/` = `agentarea-platform/libs/execution/agentarea_execution/`,
`WF/` = `EX/workflows/agent/`, `ACT/` = `EX/activities/`. The registry in
code is `ActivitySpecs()` in `registry.go`; this file explains it.

## 1. From the Python inventory to the Go set

Python defines 40 activities (34 in `libs/execution`, 5 in `libs/mcp`, 1 in
`apps/api`); its workflows schedule 31 of them. Go registers 24:

| Python activity | Go | Why |
|---|---|---|
| `build_agent_config_activity`, `resolve_model_activity`, `discover_available_tools_activity`, `discover_tool_providers_activity`, `resolve_agent_tools_activity` | `resolve_run_config_activity` | decision 3c: one first activity resolves everything into `api.RunConfig` |
| `update_task_status_activity`, `publish_workflow_events_activity`, `materialize_skill_files_activity` | not ported | scheduled only on runs recorded before the task log (`task-log-record-v1` unpatched, `WF/base.py:505-545`, `WF/disclosure.py:399`) |
| `discover_runtime_manifest_activity`, `create_execution_plan_activity`, `evaluate_goal_progress_activity`, `store_history_chunk` | not ported | registered, never scheduled |
| `update_mcp_instance_status_activity`, `discover_mcp_tools_activity`, `publish_mcp_event_activity`, `get_mcp_instance_environment_activity`, `resolve_auth_headers_activity` (`libs/mcp`) | not ported | registered on the worker, scheduled by no workflow |
| the other 23 | same name | one to one |

Names a Python activity kept stay its name so the Python source stays the
greppable specification.

## 2. Rules every activity follows

- **Principal.** Every agent-run activity acts as `Principal{workspace_id,
  user_id, agent_id}` (subject `agent:<id>`, Python `dependencies.py:200`);
  an activity fails if any is missing.
- **Kind** (decision 3d). `control`: reads or writes definitions, the task
  row, the ledger, audit, caps, billing, schedules. `data`: model calls, tool
  calls, content (task log reads, context store, sandbox, runner).
- **Resolve once** (decision 3c). After `resolve_run_config_activity` no
  activity reads an agent, model, provider, MCP instance, server spec, OpenAPI
  connection, catalog entry, skill row, project or delegate. The workflow
  passes each activity the slice of `RunConfig` it needs (a model call gets
  `ResolvedModel`, a tool call the one `ToolBinding`).
- **Live reads** allowed after resolve, because they change during a run by
  design or are values, not definitions: credential values by reference
  (provider key named by `APIKeySecret`, MCP auth headers and OAuth refresh by
  `AuthConfigID`, env secrets, delegate bearer by `AuthSecretName`); current
  spend caps and month-to-date ledger sums (Python patch
  `current-spend-caps-v1`); billing holds and quotes; wallet balance, keys and
  settled payments; skill package bytes by `Skill.Package`; the task log
  window; the platform toolsets (below).
- **Non-retryable failures** are `durable.ApplicationError` with
  `NonRetryable: true` and the Python type names the workflow branches on:
  `AgentNotFoundError`, `ModelInstanceNotFoundError`, `NoModelBoundError`,
  `GovernanceDeniedError` (incl. billing refusal, `interceptor_name:
  "billing"`, `entitlement_code`), `EscalationRequiredError`,
  `SpendCapReachedError`, `ReasoningSettingError`, `TaskNotFound`,
  `TaskLogRejected`, `SkillActivationFailed`, `SkillActivationRefused`,
  `SkillNotFound`, `SkillUnreadable`, `ReservedToolName`; retryable
  `ServiceUnreachable` drives the outage wait. Trigger activities keep their
  own lists (`EX/workflows/trigger_execution_workflow.py:117-170`).
- **Retry defaults** (`EX/workflows/constants.py`, `retry.py`): plain 3
  attempts from 1 s; bookkeeping 10 attempts, max 30 s; model call 8 attempts,
  2 s to 60 s; backoff 2. Heartbeat timeout 30 s, heartbeats every 2 s
  (`AGENTAREA_TEMPORAL_*`, kernel `durable.Config.HeartbeatThrottle`): a stop
  reaches an activity only through its heartbeat.
- **Governance gate.** Python wraps `call_llm_activity` (pre and post),
  `execute_mcp_tool_activity` (pre and post) and the tool discovery (post) in
  `GovernanceWorkerInterceptor` (Cost, Token, Service budget guards,
  `entitlement_guard` extension, prompt-injection detector, metrics;
  `libs/governance/.../factory.py:27-67`). In Go it is an activity-inbound
  interceptor registered by this package, asking `governance/api` and
  `ext.entitlement_guard`; the discovery post phase runs inside
  `resolve_run_config_activity`. The worker refuses to start without the
  gated activities registered (`validate_activity_mapping`).

## 3. The activities, in implementation order

Columns of each entry: Python source and the workflow call site; queue; in →
out; side effects; options; dependencies (other modules' `api`, kernel ports,
`ext`); billing. Steps are the order in `ActivitySpecs()`.

There is no mixed fleet, so an activity is not "moved" into production: each
is built and tested alone (Temporal activity test environment, store tests on
real Postgres) in this order, and the Go `AgentExecutionWorkflow` serves
flagged agents only once steps 1 to 12 exist. Steps 13 and 14 belong to phase
3 (reconciler, cron sync, triggers).

### Step 1. Context store: `store_context_output`, `read_context_output`, `search_history` (data)

- Python `ACT/agent/context.py:93-147`; `WF/context_tools.py:58,162,208`.
- `StoreOutputRequest` / `ReadOutputRequest` / `SearchHistoryRequest` →
  `ContextResult`. Failure is reported in `error`, never raised.
- Effects: blob put/get/grep under `tasks/{workspace}/{task}/outputs/{id}.json`
  and `.../history/chunk_{n}.json` (`EX/workflows/context_store.py:43`).
  Store runs for outputs over 8000 chars when the strategy offloads; read
  returns at most 16 000 chars.
- 5 min, 2 attempts. Deps: kernel `blob`. Billing: none.

### Step 2. `recall_history_activity` (data)

- Python `ACT/agent/context.py:41`; `WF/context_tools.py:100`.
- `RecallHistoryRequest` → `RecallHistoryResult`. Reads the task feed rows by
  type; an unknown type is refused with the list of known ones.
- 5 min, 2 attempts. Deps: runs store (task log). Billing: none.

### Step 3. `delegated_task_spend_activity`, `check_monthly_spend_cap_activity` (control)

- Python `ACT/agent/task_state.py:239,172`; `WF/delegation.py:176`,
  `WF/budget.py:217`.
- `DelegatedSpendRequest` → `DelegatedSpendResult` (child's ledger sum);
  `MonthlySpendCapRequest` → `MonthlySpendCapResult` (month-to-date for the
  workspace, the agent's own lines, LLM caps; `current_caps` reads the caps
  set now instead of the frozen ones).
- Read only. Spend 5 min 3 attempts; cap check 5 min bookkeeping.
- Deps: runs store (`cost_entries`), `governance/api` (current caps),
  `money.CustomerPricing` (currency). Billing: none.

### Step 4. `deliver_to_runner_activity` (data)

- Python `ACT/agent/runner.py:20`; `WF/runner_turn.py:540`.
- `DeliverToRunnerRequest` → nothing. Publishes a notify on
  `clients.{client_id}.runner` (steer, decision or pause); booleans travel as
  lowercase strings.
- 5 min, bookkeeping. Deps: kernel `events` (pub/sub). Billing: none.

### Step 5. `validate_artifacts_activity` (data)

- Python `ACT/agent/files.py:214`, `ACT/artifact_validation.py`;
  `WF/completion.py:399`.
- `ArtifactValidationRequest` → `ArtifactValidationResult` (passed, failed,
  unavailable; fail closed). Persists the declared sandbox files into the
  workspace artifacts through the sandbox file API and checks them.
- 5 min, 3 attempts. Deps: `sandbox/api` (file API, `SANDBOX_FILE_SECRET`),
  runs store (workspace artifacts), kernel `blob`. Billing: none.

### Step 6. `resolve_run_config_activity` (control): the first activity

- Python `build_agent_config_activity` (`ACT/agent/config.py:458`),
  `resolve_model_activity` (`ACT/agent/llm.py:161`),
  `discover_available_tools_activity` (`config.py:608`),
  `discover_tool_providers_activity` (`config.py:667`),
  `resolve_agent_tools_activity` (`config.py:721`); `WF/initialization.py:224,
  290,328,357`, `WF/delegation.py:90`.
- `ResolveRunConfigRequest` → `api.RunConfig`.
- Reads: agent (catalog built-ins included, archived refused), per-run
  selections (MCP instances, skills, files, model override), FGA
  `use_connection` for subject `agent:<id>` per attached connection, skills
  and install-policy refusals, sandbox runtime manifest, model instance, spec,
  provider config and profile (foreign parts refused), project instructions
  root first, MCP instance tools and allowed tools, OpenAPI operations,
  platform and code toolsets, delegates by saved id. Applies the disclosure
  filter and builds the bindings.
- Writes: `tasks.metadata.agent_config_hash`; selected files copied to
  `inputs/attachments/selected-<sha16>-<name>` (deterministic, a retry reuses
  the first copy); the trigger event file.
- 5 min, 3 attempts. Non-retryable: bad references, denied connections,
  archived agent, missing model.
- Deps: `agents/api`, `catalog/api`, `models/api`, `connections/api`,
  `projects/api`, `sandbox/api`, `governance/api`, kernel `authz`, `blob`.
  Billing: none.
- Changes from Python, settled by decision 3c: the model is resolved here or
  the run fails; Python's fallback to a per-call model lookup after a failed
  `resolve_model_activity` is not ported. A mid-run model change arrives
  resolved in the `change_model` command from the run surface.

### Step 7. Writers: `record_activity`, `update_task_governance_snapshot_activity` (control)

- Python `ACT/agent/record.py:70`, `ACT/agent/task_state.py:139`;
  `WF/base.py:437,472`, `EX/workflows/agent_execution_workflow.py:274`.
- `RecordRequest` → `RecordResult`; `UpdateGovernanceSnapshotRequest` →
  nothing.
- Record, in one transaction: task log rows at the workflow's seq and event id
  (bodies over 64 KiB offloaded to blob), task status and result, spend
  ledger lines derived from event rows (`ACT/agent/cost_ledger.py`:
  `llm.call.completed` → inference line with the hold to capture; tool results
  not `cost_metered`), audit rows keyed by event id, and the legacy
  `task_events` rows the enterprise usage emitter reads. Then each event row
  is published once to the `tasks.events` stream, and `live` events are
  broadcast. Idempotent by event id; retried without limit for 1 h.
  `TaskNotFound` and `TaskLogRejected` are non-retryable.
- Snapshot: `tasks.metadata.governance_snapshot`; 5 min bookkeeping.
- Kind: control, because the status, ledger and audit lines must commit with
  the rows. It is written as two store calls behind two ports (content rows;
  index, ledger, audit) in one transaction, so a later split is two activities.
- Deps: runs store (`tasks`, `task_conversation_entries`, `task_events`,
  `cost_entries`), `governance/api` (audit sink, `ext.audit_sink`), kernel
  `events` (outbox + Redis streams, never Redis only), `blob`, `money`.
- Billing: no call; writes the ledger lines with `hold_id` and
  `settle: capture` that the settlement worker captures through
  `money.ToolBilling.Capture`.
- Tests: store tests on postgres with the goose baseline.

### Step 8. `activate_skill_activity` (data)

- Python `ACT/agent/files.py:226`; `WF/disclosure.py:304` through
  `_execute_through_outage`.
- `ActivateSkillRequest` → `ActivateSkillResult` (sizes and links only; the
  text never enters history). Reads SKILL.md and the package by pointer
  (blob, or GitHub), writes the package into the task's sandbox workspace,
  appends the log entry at the reserved seq and id.
- Heartbeat 30 s; schedule-to-close = the run's `OutageWait.RetryWindow`,
  start-to-close min(5 min, window), unlimited attempts 2 s to 60 s; after the
  window the workflow waits out the outage (`ServiceUnreachable`).
- Deps: `sandbox/api`, runs store, kernel `blob`, GitHub over `netguard`.
  Billing: none.

### Step 9. `create_delegation_task_activity` (control)

- Python `ACT/agent/task_state.py:253`; `WF/delegation.py:273`.
- `CreateDelegationTaskRequest` → `CreateDelegationTaskResult`. Creates the
  child task with the parent policy as upper bound and `run_budget`, records
  the child workflow id. The child is started by the parent as a child
  workflow, not here; the child's own first activity resolves its config.
- 5 min, 3 attempts. Deps: runs service (task creation), `governance/api`
  (policy resolution), `agents/api`. Billing: none.

### Step 10. `run_runner_turn_activity` (data)

- Python `apps/api/.../harness_runner.py:441`; `WF/runner_turn.py:135`.
- `RunnerTurnRequest` → `RunnerTurnResult`; while it runs it signals
  `runner_turn_update` (`RunnerTurnUpdate`) to the run.
- Queue `api.RunnerTaskQueue(client_id)`, polled by the `serve` process
  holding the client's runner WebSocket (a worker inside serve, plan phase 2
  item 3). Start-to-close 12 h, schedule-to-start 10 min, heartbeat 30 s, 1
  attempt, waits for cancellation; the workflow retries a lost turn up to 5
  runners with a 5 s delay.
- Deps: runs handlers (runner socket), kernel `durable` (signal). Billing:
  none (the CLI pays its own model).

### Step 11. Model calls: `call_llm_activity`, `compact_messages_activity` (data)

Only after the Go `ext.tool_billing` and `ext.entitlement_guard`
implementations exist (plan phase 2 item 2): a platform-funded call with
billing installed and no hold is an error.

- Python `ACT/agent/llm.py:242,292`; `WF/llm_turn.py`, `WF/completion.py:266`
  (answer check, purpose `answer_check`), `WF/compaction.py:46`,
  `WF/stopping.py:108`.
- `LLMCallRequest` → `LLMCallResult`; `CompactMessagesRequest` →
  `CompactMessagesResult`.
- Effects: writes the request's pending messages and reads the window from
  the task log; spend-cap refusal from current caps and the ledger; billing
  hold before the credential read; credential value read; HTTPS stream to the
  provider (`localhost` rewritten to the deployment's local host); cumulative
  chunk snapshots broadcast live every 0.1 s (reply text withheld when
  `stream_text` is false); quote after the call; void on failure. Compaction
  also stores the summarised entries as a history chunk when asked.
- 10 min, heartbeat 30 s, model-call retry, waits for cancellation; an
  interruption with no cancel request is retried.
- Deps: `models/api` (transports, provider credentials), `governance/api`
  (guards), kernel `secrets`, `events` (live), `blob`, `money`, runs store.
- Billing: platform-funded (`ManagedBy == "platform"`):
  `ToolBilling.Authorize(kind=model)` → refusal is `GovernanceDeniedError`
  billing; `Quote` after the call gives `usage.billing` (`ChargeLine`, settle
  capture); `Void` when the call did not run to an answer. Workspace-funded:
  none. `SpendCapReachedError` ends the run on the cap.

### Step 12. `execute_mcp_tool_activity` (data): every regular tool call

- Python `ACT/agent/tools.py:398`, `libs/governance/.../tool_calls.py:442`;
  `WF/tools.py:75`, `WF/stopping.py:141`.
- `ToolCallRequest` → `ToolCallResult`. Dispatch by `Binding.Source`: MCP
  (streamable HTTP, SSE or the gateway; signed call context; progress relayed
  as `tool.progress` and heartbeats), OpenAPI operation (402 paid from the
  wallet), code toolsets (files, web, media, shell, math, context, triggers,
  and the platform toolsets), remote A2A delegate.
- Effects: policy re-decision with the workflow's approval; audit
  allowed/denied rows (denial keyed `uuid5("tool-denied:{run}:{activity}")`);
  cost declaration, billing hold, spend-cap gate; the call; ledger lines
  (`cost_metered`); wallet payments (x402, MPP) and their records; outputs
  over 8000 chars and images offloaded to blob; sandbox shell runs.
- 40 min, heartbeat 30 s, 3 attempts, waits for cancellation.
- Deps: `connections/api` (MCP client, auth headers, OAuth refresh under the
  advisory lock, OpenAPI execution), `sandbox/api`, `wallet/api`,
  `governance/api` (PDP, audit), `models/api` (media models), every module
  `api` a platform toolset calls, kernel `secrets`, `netguard`, `blob`,
  `events`, `money`, `ext.egress_exits`.
- Billing: platform-funded connector `ToolBilling.Authorize(kind=tool)`,
  `Void` on failure, ledger line with `settle: capture`; media model calls
  as step 11 (`model_billing`); wallet payments are the wallet's, not
  `tool_billing`.

### Step 13. `start_undispatched_tasks_activity`, `sync_cron_schedules_activity` (control, phase 3)

- Python `ACT/undispatched_task_activities.py:29`,
  `ACT/cron_schedule_sync_activities.py`; their schedule workflows (every
  1 min and 5 min, overlap skip).
- Start every task with no workflow (`StartUndispatchedResult`); keep one
  Temporal schedule per cron trigger. 5 min, 1 attempt.
- Deps: runs store, `streams/api`, kernel `durable` (Executor, Scheduler).
  Billing: none.

### Step 14. Triggers (control, phase 3, trigger queue)

- `evaluate_trigger_conditions_activity` → `EvaluateTriggerConditionsResult`:
  3 min, heartbeat 30 s, 5 attempts 1 s to 2 min. Any error means "conditions
  not met" (kept). Its LLM condition is a model call billed as step 11
  (`libs/triggers/.../llm_condition_evaluator.py:571,883`).
- `execute_trigger_activity` → `ExecuteTriggerResult`: creates the task with
  the schedule tick's deterministic id and starts its run; 12 min, heartbeat
  2 min, 3 attempts 2 s to 8 min.
- `record_trigger_execution_activity` → `RecordTriggerExecutionResult`: 2 min,
  5 attempts 1 s to 30 s.
- `fire_trigger_batch_activity`, `close_trigger_batch_activity` (`OpenBatch`
  → `BatchResult`): 5 min, retried without limit, 2 s to 5 min.
- Deps: `streams/api`, runs service, `models/api`, kernel `durable`.

## 4. Open points

1. Platform toolsets (20 namespaces, `code_tools_loader.py:23-60`) are the
   control API exposed as agent tools; in Go each calls its module's `api`.
   Step 12 reaches parity only as those modules' `api` packages exist
   (phase 5), or the toolsets stay unavailable to Go runs until then.
2. Step 11 waits on the enterprise repo's Go `ext.tool_billing` and
   `ext.entitlement_guard`.
3. Step 12's wallet path needs Go x402 and MPP libraries; not yet checked
   (review-fable 2.2).
