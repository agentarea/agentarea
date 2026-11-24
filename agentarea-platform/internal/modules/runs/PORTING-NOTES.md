# runs: porting notes

Python paths are relative to `agentarea-platform/libs/execution/agentarea_execution/workflows/`.

## Fixed Python bugs

- `get_workflow_events` and `get_latest_events` are gone. Python always
  answered an empty list, because events are published as they happen and the
  event manager never keeps any (`agent_execution_workflow.py:352`, `:357`).
  No client queries them: not the webapp, the CLI or an MCP tool. A run's
  events are read from its task events.
- A cron firing that failed after its last attempt is recorded with the
  activity's own error message and `error_type` ApplicationError, and the
  workflow fails with that error. Python's `except ApplicationError` never
  caught an activity failure (it arrives as ActivityError), so every failure
  was recorded as "Unexpected error: Activity task failed"
  (`trigger_execution_workflow.py:201`, `:239`, `:256`). A timeout or cancel
  is still recorded as unexpected, but with its own cause. The webapp's
  trigger executions table shows `error_message` as text.
- Cost settlement (`agentarea_tasks/cost_settlement.py`, `vendor_settlement.py`)
  runs as the worker's `cost settlement` loop (`service/settlement.go`,
  `Module.Settlement()`). Pending conversions of model lines were quoted as
  tool kind (`_convert` called `convert_cost` with the default `KIND_TOOL`), so
  a model line got the tool markup. Go quotes them as `KindModel`, test
  `TestSettlementConvertsAPendingConversion`.
- Two workers could settle one line twice: `claim_unsettled` filters
  superseded lines in the statement that waits on the row lock, and READ
  COMMITTED does not re-check NOT EXISTS after the wait, so a worker that
  locked a line just after another committed its successor captured the hold
  again (only the billing idempotency key hid it). Go drops claimed lines that
  a committed line supersedes before settling them (`store.DropSuperseded`),
  test `TestSettlementSharesLinesAcrossWorkers` (4 workers, 45 lines, one
  capture each).
- A model or tool charge without a hold carries `settle: ""` in Go's event payload where
  Python had None (stripped from evidence), so every model line waited on settlement and
  the loop logged it each tick. `domain.CostLines` drops the empty `settle` and `hold_id`,
  test `TestAChargeWithoutSettlementDoesNotWaitOnOne`.
- Pending conversions were quoted with the connector's markup; Python's
  `convert_cost` is "without markup". Go quotes them with payer `workspace`,
  same test.

## Deviations

- `api.Policy` reads and writes the stored snapshot names (`run_budget_usd`, `*_spend_cap_usd`,
  `service_budget_usd`, `spend_caps[].amount_usd`, `prompt_injection_detection_enabled`), the ones
  task_service.py and governance `Snapshot.Stored()` write; `workflows/snapshot_test.go` reads both.

- Approvers by pattern: Python tries the `approvers_by_tool` patterns in the
  order the dict was written (`helpers.py:299`). Go tries them sorted, because
  the policy arrives as a JSON object with no order.
- Every `workflow.patched(...)` gate takes its patched branch only. Go has no
  Python histories to replay.
- The JSON parse error inside "arguments must be valid JSON: ..." (completion,
  wait) is Go's decoder text, not Python's.
- A malformed connector cost declaration refuses the call with "the cost of
  this call cannot be known: ...". Python refuses it earlier, when it builds
  the connection (`agentarea_common/tool_cost.py` `tool_connection`).
- The entitlement gate's `ExecutionState` carries only the budget and token
  limits of `to_execution_state` (`governance/domain/policies.py:305`), not
  execution limits, tools, escalation rules, content safety or the run's
  counters.
- `deliver_to_runner_activity` leaves out empty string fields. Python leaves
  out only `None` (`agent/runner.py:30`), and Go cannot tell the two apart.
- `read_file` of a file that is not UTF-8 answers "Error reading file: 'utf-8'
  codec can't decode the file". Python names the byte and its position
  (`file_toolset.py` read_file).
- Skill files are committed without the `{"source": "skill", ...}` provenance
  (`agent/files.py:86`), because sandbox TaskWorkspace.PutFiles takes none.
- `capability_unavailable.runtime_version` stays empty, because sandbox
  ArtifactValidation does not carry it.

- Trigger firings and the cron sync read and write triggers through ports
  that runs declares (`service.Triggers`, `service.TriggerBatches`), because
  triggers belong to streams. The trigger activities and workflows are ported;
  what they call is not.

## Not ported

- The legacy skill path, where SKILL.md is in workflow history and files are
  materialized (`agent/disclosure.py:382`). Python schedules it only on runs
  started before the task log that never took the patch; Go has no such runs.
  Only the package path through `activate_skill_activity` exists.
- The streams side of the trigger ports: listing cron triggers, condition
  evaluation, firing a trigger into a task, recording a trigger execution,
  firing and closing a stream batch (`agentarea_triggers`
  `trigger_service.py`, `batch_service.py`). `agentarea worker` refuses to
  start until streams implements them.
- The `agentarea worker` start also waits on these ports, which their owners
  have not ported: run definitions (connections, catalog, projects), skill
  packages (catalog) and tool callers (connections).

## HTTP surface (`handlers/`, `service/surface_*.go`)

Python paths here are relative to `agentarea-platform/`.

- Done: `StartDefinition` (`service/surface_definitions.go`, `api.DefinitionRuns`) serves `POST /task-definitions/{id}/run` and the MCP `task_definitions_run` through `Surface.start` with `created_via`, the definition id in the provenance, and refusals rendered with their own status; wired by `app/taskdef_runner.go`.

### Fixed Python bugs

- Cancelling a scheduled task whose workflow was cancelled but whose row
  failed to update answers 500. Python swallowed the error and answered 404
  "Task not found or already completed" with the workflow already gone
  (`libs/tasks/agentarea_tasks/temporal_task_manager.py:315`). Test:
  `TestCancellingAScheduledTaskReportsAFailedWrite`.
- A bad `parameters` value (a reserved trigger key, a `model_override` that is
  no id) is a 422 on `body.parameters` on every create route. Python's sync and
  schedule routes caught RunCreate's ValidationError as a ValueError and
  answered 404 "Agent validation error" (`apps/api/agentarea_api/api/v1/agents_tasks.py:1228`,
  `:1337`). Test: `TestCreateBodyRefusesTriggerParametersAtTheField`.
- A run whose workflow cannot start is stored failed with the error "Task
  dispatch failed" and the route answers 503 (the stream: an `error` frame,
  `error_type` creation_failed). Python stored the exception's own text as the
  task error and answered 200 with the failed task, or a `task_failed` frame
  (`libs/tasks/agentarea_tasks/temporal_task_manager.py:232`). Test:
  `TestCreateRefusals`.
- `GET /inbox/decisions` answers `agent_id: null` for an audit row whose
  `agent_id` is no UUID. Python's response model refused the row, so the whole
  page was a 500 (`apps/api/agentarea_api/api/v1/inbox.py:55`). Test:
  `TestDecisionsAnswerNullForAMalformedAgentID`.

### Deviations

- A workflow Temporal reports continued-as-new or timed out reads as
  `running`, because `durable.Executor.Status` answers those as unknown with no
  error (`apps/api/.../temporal_workflow_service.py` get_workflow_status).
- Sanitized and revealed tool values keep the JSON key order the row stored;
  `sanitize_tool_event_value` scalars still go through `domain`, which sorts
  the keys of maps it builds.
- `mask_inline_secrets`: Go's `\w` and `\b` are ASCII; the `(?<![\w-])` and
  `(?<!\S)` lookbehinds are checked by hand and the `_ASSIGNMENT` backreference
  is spelled out per quote (`libs/common/agentarea_common/events/redaction.py`).
- The live hub tails `tasks.events` and the task live channels through
  `events.Broker`; event data maps arrive unordered and are sorted by key.
- `requires_task_authority` runs once `task_id` is a valid UUID, before the
  route's other parameters and body are validated, as FastAPI orders it.
  `requires("execute", "agent")` on the create routes runs the same way on
  `agent_id`; a refusal is 403 "Permission denied".
- One start path (`service.Surface.start`) serves the three create routes and
  `api.Tasks.Submit`: governance `RunPolicies.Task`, the monthly caps, the agent
  (archived, model), the row with its `governance_snapshot`, then the launch.
  Python had `start_run`, `reserve_run` + `dispatch_reserved_run` and
  `create_and_execute_task_with_workflow` with the same steps in slightly
  different orders. An unknown agent found there is 404 "Agent not found" (the
  stream: `error_type` agent_not_found), not "Agent validation error".
- The streaming create answers a refused run with its `error` frame only when
  the request had no attachments; with attachments every refusal is an HTTP
  answer, as Python's reserve path raised them.
- `GET .../status` leaves out `message`, `session_id` and `usage_metadata`:
  the orchestrator never set them, so Python always answered null.
  `execution_time` is end minus start in seconds, null while running.
- `parameters` validation on create checks the reserved keys and
  `model_override`; the reasoning keys are checked when the run builds its
  configuration, not at the route.
- The conversation rebuild counts a turn's tool calls from the row's
  `tool_calls`; a turn whose calls were offloaded (`tool_calls_ref`) counts 0
  toward `tool_calls_used`.
- `Tasks.Submit` copies the parameters it is given; a session follow-up routes
  only when a candidate's capability selection and creator match, as
  `_try_route_to_active_workflow` does, and a scheduled submit never routes.

### Not mounted (provider missing at finish)

- The runner routes mount only with `AGENTAREA_MCP_GATEWAY_SECRET` (turn
  tokens and live turns); without it serve logs what is missing.
- Approval `hint` is null until connections implements `service.ToolHints`
  (`api/v1/tool_call_approvals.py:78`); the list answers null as Python does.
- The create, retry and continue routes mount only when app passes
  `Policies`, `Launcher` and `Permissions` (retry also `Resumer`); the file
  routes only with `TaskFiles`; `change_model` answers 500 without `Models`.

## Runner (`runner/`, `runner_surface.go`)

`GET /v1/runner/whoami`, `PUT /v1/runner/tasks/{id}/files/{path}` and the
socket `/v1/runner/connect` (`v1/harness_runner.py`,
`agentarea_tasks/harness_protocol.py`, `harness_runner_connection.py`).

### Deviations

- A stopped turn's last report is signalled with a context that outlives the
  activity's cancellation (`RegisterRunnerTurns`, not `Activities.RunRunnerTurn`).
- A refused socket is HTTP 403 before the upgrade, never an accepted socket
  closed at once; a binary frame closes 1003 (Python 1011).
- The upload's path is read from the decoded URL path after `/files/`, with
  empty and `.` segments dropped as `PurePosixPath` does; `..`, an absolute or
  an empty path is 422.
- The content type guessed for an upload is Go's `mime` table, parameters
  stripped: an extension Go does not know (such as `.md` on a bare host) is
  `application/octet-stream`.
- `welcome.turns` is always empty, as Python sends: a reconnecting runner's
  turns are assigned again by their runs.


## An agent acts as itself (2026-11-15)

A run calls as `{UserID: starter, Subject: Agent}`, and a runner turn token is
agent-subject too. Every run check compared only the user id, so an agent
inherited its starter's authority. Python has the same gap; fixed here with
`authn.Principal.ActsAsAgent()`:

- Human only, refused before the run is read (403 on HTTP, a tool refusal on
  the platform tools): resolving an escalation, answering input
  (`SendInput`/`SubmitInput`), an A2UI action, `ContinueRun`/`ContinueExecution`
  and the `update_budget` command.
- `callerCanApprove` (CallerCanApprove for a person) and `mayResolve` are false
  for an agent, whatever the approvers list says, so escalation listings and
  tool-call approvals show it nothing to decide.
- Kept from Python: an agent may cancel, pause, resume, retry and queue a
  message on a run its starter started (`_task_authority.py` compares only
  `user_id`); a workspace admin path never applies (`Admins.IsAdmin` refuses
  agents).
- Tests: `service/agent_authority_test.go`. No behaviour-suite test: the
  harness cannot issue an agent-subject call without a live run whose model
  calls a platform tool with chosen arguments.

## Settlement claims (2026-11-15)

- Python held one write transaction, and the claimed lines' row locks, across
  every Capture and vendor call of a batch. Go claims due lines SKIP LOCKED in
  `cost_settlement_claims` (core goose `00004_cost_settlement_claims.sql`, a
  table of its own so the ledger stays append-only) and commits; settles each
  line with no transaction open; then writes the successor, or the outcome, in
  a short transaction. A claim lasts `settleLease` (10 min): a worker that dies
  leaves its lines to others after that. Tests
  `TestSettlementHoldsNoTransactionWhileBillingAnswers`, `TestADeadWorkersClaimExpires`.
- A failed settlement backs off: the claim keeps the line for
  tick * 2^failures, at most an hour (`TestAFailedSettlementBacksOff`). A line
  billing rejects (`money.ErrBillingRejected`, wrapped by the ToolBilling for
  an invalid request or a 4xx) and a line of an invalid workspace are marked
  dead and never claimed again; Python retried both every tick
  (`TestALineBillingRejectsIsDead`, `TestALineOfAnInvalidWorkspaceIsDead`).
- A platform-paid tool call's billing hold was keyed `hold:<callRef>:<random>`,
  so each activity retry held again and leaked the last hold. It is keyed
  `hold:<callRef>` (`TestARetriedPlatformCallReusesItsHold`).
- A model call's charge line carried no `vendor_currency` (Python's
  `ModelCharge.as_billing` does, `PROVIDER_CURRENCY`), so a held model line
  settled with an empty currency and billing refused every capture. The line
  carries USD (`TestAHeldModelLineCarriesItsVendorCurrency`).
