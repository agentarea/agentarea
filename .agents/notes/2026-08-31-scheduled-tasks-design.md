# Scheduled tasks — one-shot execution at an absolute time

**Date:** 2026-08-31
**Status:** proposed, awaiting approval
**Scope:** run a task once, at a moment the user picks. Recurring scheduling stays with cron triggers.

## Problem

There is no way to say "run this once, tomorrow at 15:00".

`TriggerType` offers `cron`, `webhook`, `polling` (`libs/triggers/agentarea_triggers/domain/enums.py`). Cron is recurring by
construction and cannot express a year, so a "one-shot" cron such as `0 15 30 8 *` means *every* 30 August. Nothing stops it
after the first run: the only auto-disable counts consecutive *failures* (`trigger_service.py:548`), and there is no
execution-count limit on the model.

The gap is already visible in the agent-facing surface. `TriggersToolset.create_cron` currently instructs agents to fake
one-shot scheduling (`apps/api/agentarea_api/tools/triggers_toolset.py:118-122`):

> For one-shot reminders set day-of-month + month so the cron only matches the intended date.

That advice produces a trigger that silently re-fires a year later and leaves dead configuration in `/triggers`.

## Options considered

### A. `run_once: bool` on the cron trigger — rejected

The date would still be encoded in a cron string that cannot hold a year, so "when does this run" is unreadable and
undecidable without a cron evaluator. It is also a flag that is meaningless on its own: it only has semantics paired with
`cron_expression`.

### B. `max_executions: int | None` on the cron trigger — rejected

Sounds more general than it is:

- Temporal already owns this counter. `ScheduleState.limited_actions` / `remaining_actions` (`temporalio/client.py:6361-6369`)
  is decremented server-side, so our column becomes a second source of truth that goes stale; rendering "2 runs left" would
  still require a `describe` call.
- It counts schedule *actions* (workflow starts), not successful executions. Our `TriggerExecution.status` distinguishes
  `success` / `failed` / `timeout`, so "run 3 times" would burn 3 starts even if 2 failed — a semantic mismatch users will
  read as a bug.
- No real demand for "run exactly N times". The demands are "once at T" and "repeatedly until T".

### C. New `TriggerType.SCHEDULED` with `run_at: datetime` — rejected

Mechanically cheap (the trigger table is single-table with nullable per-type columns, `infrastructure/orm.py:33-52`) and it
would ride the existing schedule lifecycle via `ScheduleSpec(calendars=[ScheduleCalendarSpec(year=...)])` plus
`ScheduleState(limited_actions=True, remaining_actions=1)`.

Rejected on fidelity. A trigger describes a task with `agent_id` plus a flat `task_parameters` dict
(`libs/triggers/agentarea_triggers/schemas/dto.py`). It carries no `project_id`, no `task_policy`, no `attachments` — all of
which a real task has (`TaskCreate`, `apps/api/agentarea_api/api/v1/agents_tasks.py:83-91`). Scheduling a rich task through a
trigger would drop those fields or force a second, divergent copy of the task payload. A one-shot trigger is also permanent
dead config in the `/triggers` list once spent.

### D. `scheduled_at` on the task itself — **chosen**

The scheduled thing *is* a task: same description, parameters, attachments, project, policy. It appears in the task list where
users already look, cancels through the existing cancel path, and needs no new top-level concept. The platform already has the
seam for it — `TaskService.reserve_run` persists a task without dispatching, and `dispatch_reserved_run` releases it
(`libs/tasks/agentarea_tasks/task_service.py:409-461`).

### E. `end_at` on cron triggers — out of scope, complementary

"Every weekday at 9:00 until 30 September" maps to `ScheduleSpec(end_at=...)`, one nullable column. Real, but a different
feature; it does not solve one-shot and one-shot does not solve it. Tracked as a follow-up.

## Design

### Relationship to triggers: what is one-shot and what is recurring

`scheduled_at` is strictly one-shot. It is never a recurrence rule, and the `scheduled` status never appears on a task created
by a trigger.

This is not an arbitrary split. A task is a single execution: one `execution_id`, one `result`, one `started_at` /
`completed_at`, one event stream. A "repeating task" has no coherent answer for what its result is, so repetition lives one
level up. That is already how cron works today — every firing runs `TriggerExecutionWorkflow`, which mints a *new* task via
`create_task_from_trigger_activity`. Tasks born that way are created at fire time and start at `pending`.

So: **task = one execution, trigger = a factory of tasks.**

In the UI the two need not look like two places. A single "Run later" control with a repeat toggle covers both: no repeat
creates a scheduled task, repeat creates a cron trigger. One entry point, two correct data models beneath it.

### Data

- `TaskORM.scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)`.
  Deliberately **timezone-aware**, unlike the neighbouring `started_at` / `completed_at`, which are naive
  (`libs/tasks/agentarea_tasks/infrastructure/orm.py:28-29`). A future instant that loses its offset is a scheduling bug
  waiting to happen; do not copy the existing naive columns.
- Index on `(workspace_id, status, scheduled_at)` to keep the "upcoming" listing cheap.
- Add `"scheduled"` to the valid status set (`libs/tasks/agentarea_tasks/domain/base_service.py:379-390`).
- Alembic migration named with an ISO timestamp, per repo convention.

### Domain

- `AgentTask.scheduled_at: datetime | None`.
- Validation at creation: must be timezone-aware and strictly in the future. A naive datetime is rejected with 422 rather
  than silently assumed to be UTC.

### Dispatch

Temporal's own delayed start does the waiting; no poller, no new daemon, no second lifecycle.

- `WorkflowConfig` gains `start_delay: timedelta | None` (`libs/common/agentarea_common/workflow/executor.py:40-47`).
- The Temporal executor threads it into `client.start_workflow(..., start_delay=...)` (supported by the pinned SDK,
  `temporalio/client.py:385`).
- `TemporalTaskManager.submit_task` (`libs/tasks/agentarea_tasks/temporal_task_manager.py:119`): when `task.scheduled_at` is
  set, compute `start_delay = scheduled_at - now`, start the workflow, persist `execution_id`, and set status `"scheduled"`
  instead of `"running"`. The workflow moves itself to `running` when it actually begins.
- `DirectTaskManager.submit_task` raises a typed error when `scheduled_at` is set. It has no timer; silently running the task
  immediately would be exactly the kind of fallback this codebase forbids.

Consequence, accepted deliberately: the workflow payload is frozen at scheduling time, as is the policy/model resolution done
by `create_task_with_policy(require_model=True)`. "What you scheduled is what runs." If late binding is ever needed, the
alternative is a dispatcher that calls `dispatch_reserved_run` at T; that is a bigger change and is not needed now.

### API

- New `POST /v1/agents/{agent_id}/tasks/schedule` → `201 TaskResponse`. Body is `ScheduleTaskCreate(TaskCreate)` with a
  required `scheduled_at`.
- The existing `POST /v1/agents/{agent_id}/tasks/` stays exactly as it is. It returns an SSE stream; making its response type
  conditional on a request field would poison the generated OpenAPI client the webapp depends on. A separate route keeps one
  response type per operation.
- Attachments reuse the existing sequence: stage → `reserve_run` → commit → schedule (instead of `dispatch_reserved_run`).
- `TaskResponse` exposes `scheduled_at`; `GET /v1/tasks/` supports `status=scheduled`.
- Cancel uses the existing `/{task_id}/cancel` (`agents_tasks.py:1410`) — a delayed workflow is a live workflow and cancels
  normally. Result: status `cancelled`.
- Rescheduling is out of scope for v1: cancel and create a new one.

### MCP

- `runs_start` accepts an optional `scheduled_at`.
- `TriggersToolset.create_cron`'s docstring drops the one-shot-via-cron recipe and points at scheduled runs. Leaving it would
  keep agents building triggers that re-fire in a year.

### Webapp

- Task list: `scheduled` badge and the local-time run moment; upcoming tasks ordered by `scheduled_at`.
- Run form: a "Run later" datetime control that targets the schedule endpoint.
- Regenerate the API client (`pnpm generate:api`) after the backend lands.

### Errors

- Past or naive `scheduled_at` → 422.
- Temporal unavailable while scheduling → 503, and the reserved task is marked `failed` rather than left in `preparing`,
  matching the existing dispatch failure path.
- No silent fallbacks anywhere in the chain.

### Testing

TDD, tests first.

- Unit: naive/past `scheduled_at` rejection; `TemporalTaskManager` delay computation and the `scheduled` status; the
  `DirectTaskManager` rejection.
- Integration: schedule endpoint produces a task row with `status=scheduled` and an `execution_id`; cancel moves it to
  `cancelled`; a Temporal time-skipping test proves the workflow does not run before T and does run after.
- The DB-enforced pieces (nullable/index/status constraint) belong in the migrations-gate suite — mocked sessions have no FKs
  and would report green regardless.

## Risks

- Very long delays (months) hold an open workflow. Temporal timers are durable and open workflows are not subject to
  closed-workflow retention, but the integration test should exercise a long delay rather than only seconds.
- A delayed workflow executes whatever worker code is deployed at T, against arguments frozen at scheduling time. Acceptable,
  but worth stating in user-facing docs.

## Unrelated finding, not in scope

`TriggerService.create_trigger` swallows schedule-creation failures and returns a trigger that will never fire
(`trigger_service.py:138-146`, "Don't fail the trigger creation if scheduling fails"). That is a silent fallback and should be
fixed, but it belongs to the trigger path this design does not touch.

## Follow-ups

- `end_at` on cron triggers (option E).
- Reschedule/edit of a scheduled task.
