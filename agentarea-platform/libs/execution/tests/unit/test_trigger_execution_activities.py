"""Unit tests for trigger execution activities.

A schedule firing starts its task through TriggerService.fire, the path every
trigger kind shares, and a trigger it disables gets its schedule paused.
"""

from contextlib import ExitStack
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_execution.activities.trigger_execution_activities import make_trigger_activities
from agentarea_execution.interfaces import ActivityDependencies
from agentarea_execution.models import (
    EvaluateTriggerConditionsRequest,
    ExecuteTriggerRequest,
    RecordTriggerExecutionRequest,
    TriggerOutcome,
    TriggerSkipReason,
)
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import ConditionVerdict, CronTrigger, TriggerExecution
from agentarea_triggers.infrastructure.repository import FailureCount
from agentarea_triggers.trigger_service import TriggerService
from temporalio.testing import ActivityEnvironment

pytestmark = pytest.mark.asyncio


def _trigger(**overrides) -> CronTrigger:
    return CronTrigger(
        **{
            "id": uuid4(),
            "name": "Test Trigger",
            "agent_id": uuid4(),
            "cron_expression": "0 9 * * 1-5",
            "task_parameters": {"text": "Run the daily check"},
            "created_by": "owner",
            "workspace_id": "ws-1",
            "is_active": True,
            **overrides,
        }
    )


class _Harness:
    """The activities over a real TriggerService, with storage, tasks and Temporal faked."""

    def __init__(self, trigger: CronTrigger):
        self.trigger = trigger
        self.trigger_repo = AsyncMock()
        self.trigger_repo.get_trigger.return_value = trigger
        self.trigger_repo.disable_trigger.return_value = True
        self.trigger_repo.count_failure.return_value = FailureCount(
            trigger.consecutive_failures + 1, trigger.failure_threshold, trigger.is_active
        )
        self.execution_repo = AsyncMock()
        self.execution_repo.create.side_effect = lambda **kwargs: TriggerExecution(**kwargs)
        self.agent_repo = AsyncMock()
        self.agent_repo.get.return_value = SimpleNamespace(status="active")
        self.task_service = AsyncMock()
        self.task_service.get_task.return_value = None
        self.task_service.route_or_submit_task.side_effect = lambda task, **_: task
        self.schedule_handle = AsyncMock()
        self.client = MagicMock()
        self.client.get_schedule_handle.return_value = self.schedule_handle
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.get.return_value = SimpleNamespace(
            created_by=trigger.created_by, workspace_id=trigger.workspace_id
        )
        self.database = MagicMock()
        self.database.async_session_factory.return_value = session
        self.execute, self.record, self.evaluate = make_trigger_activities(
            ActivityDependencies(
                settings=MagicMock(),
                event_broker=AsyncMock(),
                secret_manager_factory=MagicMock(),
            )
        )

    async def run(self, activity_fn, request, *patches):
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "agentarea_execution.activities.trigger_execution_activities.get_database",
                    return_value=self.database,
                )
            )
            stack.enter_context(
                patch(
                    "agentarea_triggers.trigger_service.TriggerRepository",
                    return_value=self.trigger_repo,
                )
            )
            stack.enter_context(
                patch(
                    "agentarea_triggers.trigger_service.TriggerExecutionRepository",
                    return_value=self.execution_repo,
                )
            )
            stack.enter_context(
                patch(
                    "agentarea_agents.infrastructure.repository.AgentRepository",
                    return_value=self.agent_repo,
                )
            )
            stack.enter_context(
                patch("agentarea_tasks.task_service.TaskService", return_value=self.task_service)
            )
            for extra in patches:
                stack.enter_context(extra)
            return await ActivityEnvironment(client=self.client).run(activity_fn, request)

    def fire(self, execution_data=None, *patches):
        return self.run(
            self.execute,
            ExecuteTriggerRequest(
                trigger_id=self.trigger.id,
                execution_data=execution_data or {"execution_time": datetime.utcnow().isoformat()},
            ),
            *patches,
        )

    def submitted(self):
        return self.task_service.route_or_submit_task.await_args.args[0]


async def test_a_cron_firing_creates_a_task_stamped_with_the_trigger_as_its_origin():
    harness = _Harness(_trigger())

    result = await harness.fire()

    submitted = harness.submitted()
    assert submitted.provenance.origin_type == "trigger"
    assert submitted.provenance.origin_id == str(harness.trigger.id)
    assert submitted.provenance.correlation_id
    assert result.status is TriggerOutcome.SUCCESS
    assert result.task_id == submitted.id
    recorded = harness.execution_repo.create.call_args.kwargs
    assert recorded["task_id"] == submitted.id
    assert recorded["status"] == ExecutionStatus.SUCCESS.value


async def test_a_retried_cron_firing_reports_the_task_its_first_attempt_started():
    harness = _Harness(_trigger())
    first = await harness.fire()

    harness.task_service.get_task.return_value = SimpleNamespace(
        id=first.task_id, status="running", execution_id="wf"
    )
    second = await harness.fire()

    assert second.task_id == first.task_id
    assert harness.task_service.route_or_submit_task.await_count == 1


async def test_a_cron_trigger_that_hits_its_failure_threshold_pauses_its_schedule():
    harness = _Harness(_trigger(failure_threshold=1))
    harness.task_service.route_or_submit_task.side_effect = ValueError("no model")

    result = await harness.fire()

    assert result.status is TriggerOutcome.FAILED
    assert result.task_id is None
    assert "no model" in (result.error or "")
    harness.client.get_schedule_handle.assert_called_with(f"cron-trigger-{harness.trigger.id}")
    harness.schedule_handle.pause.assert_awaited()
    harness.database.async_session_factory.return_value.commit.assert_awaited()


async def test_a_recorded_workflow_failure_at_the_threshold_pauses_the_schedule():
    harness = _Harness(_trigger(failure_threshold=1))

    await harness.run(
        harness.record,
        RecordTriggerExecutionRequest(
            trigger_id=harness.trigger.id,
            execution_data={"status": "failed", "error_message": "boom"},
        ),
    )

    harness.schedule_handle.pause.assert_awaited()
    harness.database.async_session_factory.return_value.commit.assert_awaited()


async def test_an_inactive_trigger_is_skipped_without_a_task():
    harness = _Harness(_trigger(is_active=False))

    result = await harness.fire()

    assert result.status is TriggerOutcome.SKIPPED
    assert result.reason is TriggerSkipReason.TRIGGER_INACTIVE
    harness.task_service.route_or_submit_task.assert_not_awaited()


async def test_unmet_conditions_skip_the_firing():
    harness = _Harness(_trigger(conditions={"type": "llm", "description": "x"}))

    result = await harness.fire(
        None,
        patch.object(
            TriggerService,
            "evaluate_trigger_verdict",
            AsyncMock(return_value=ConditionVerdict(verdict="not_met", reason="quiet day")),
        ),
    )

    assert result.status is TriggerOutcome.SKIPPED
    assert result.reason is TriggerSkipReason.CONDITIONS_NOT_MET
    harness.task_service.route_or_submit_task.assert_not_awaited()


async def test_a_scheduled_trigger_whose_conditions_cannot_be_evaluated_does_not_fire():
    # field_matches must be a mapping; the evaluator cannot check this one.
    harness = _Harness(_trigger(conditions={"field_matches": ["request.method"]}))

    result = await harness.fire()

    assert result.status is TriggerOutcome.FAILED
    assert result.task_id is None
    assert result.error is not None and "condition" in result.error.lower()
    harness.task_service.route_or_submit_task.assert_not_awaited()
    recorded = harness.execution_repo.create.call_args.kwargs
    assert recorded["status"] == ExecutionStatus.FAILED.value


async def test_polled_events_are_told_to_the_agent_like_any_other_event():
    harness = _Harness(_trigger())

    await harness.fire({"extracted_events": [{"subject": "Invoice 77", "from": "a@b.c"}]})

    task = harness.submitted()
    assert task.description == "Run the daily check"
    assert task.query.startswith("Run the daily check\n\n## What started this run")
    assert "- Trigger: Test Trigger (cron)" in task.query
    assert '"subject": "Invoice 77"' in task.query


async def test_a_missing_trigger_fails_the_activity():
    harness = _Harness(_trigger())
    harness.trigger_repo.get_trigger.return_value = None

    with pytest.raises(Exception, match="not found"):
        await harness.fire()


async def test_record_trigger_execution_activity_records_what_the_workflow_reports():
    harness = _Harness(_trigger())
    task_id = uuid4()

    result = await harness.run(
        harness.record,
        RecordTriggerExecutionRequest(
            trigger_id=harness.trigger.id,
            execution_data={
                "status": "success",
                "execution_time_ms": 150,
                "task_id": str(task_id),
                "trigger_data": {"test": "data"},
            },
        ),
    )

    recorded = harness.execution_repo.create.call_args.kwargs
    assert recorded["task_id"] == task_id
    assert result.trigger_id == harness.trigger.id
    assert result.status == ExecutionStatus.SUCCESS
    harness.schedule_handle.pause.assert_not_awaited()


async def test_evaluate_trigger_conditions_activity():
    harness = _Harness(_trigger())
    event_data = {"request": {"body": {"type": "test"}}}
    evaluate = AsyncMock(return_value=True)

    result = await harness.run(
        harness.evaluate,
        EvaluateTriggerConditionsRequest(trigger_id=harness.trigger.id, event_data=event_data),
        patch.object(TriggerService, "evaluate_trigger_conditions", evaluate),
    )

    assert result.conditions_met is True
    evaluate.assert_awaited_once_with(harness.trigger, event_data)


async def test_a_task_whose_workflow_did_not_start_is_started_by_the_retry():
    harness = _Harness(_trigger())

    def stored_not_started(task, **_):
        task.status = "failed"
        task.execution_id = None
        return task

    harness.task_service.route_or_submit_task.side_effect = stored_not_started
    with pytest.raises(Exception, match="did not start"):
        await harness.fire()
    harness.execution_repo.create.assert_not_called()

    stored = harness.submitted()
    harness.task_service.get_task.return_value = SimpleNamespace(
        id=stored.id, status="failed", execution_id=None, query=stored.query
    )
    harness.execution_repo.names_task.return_value = False
    result = await harness.fire()

    harness.task_service.restart_undispatched_task.assert_awaited_once()
    assert result.status is TriggerOutcome.SUCCESS
    assert result.task_id == stored.id
    recorded = harness.execution_repo.create.call_args.kwargs
    assert (recorded["task_id"], recorded["status"]) == (stored.id, ExecutionStatus.SUCCESS.value)


async def test_a_retry_records_the_firing_an_attempt_that_died_did_not():
    harness = _Harness(_trigger())
    first = await harness.fire()
    harness.task_service.get_task.return_value = SimpleNamespace(
        id=first.task_id, status="running", execution_id="wf"
    )
    harness.execution_repo.create.reset_mock()

    harness.execution_repo.names_task.return_value = True
    await harness.fire()
    harness.execution_repo.create.assert_not_called()

    harness.execution_repo.names_task.return_value = False
    await harness.fire()
    recorded = harness.execution_repo.create.call_args.kwargs
    assert recorded["task_id"] == first.task_id
