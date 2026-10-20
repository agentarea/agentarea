"""A condition that turns an event away is the filter working, not the trigger failing."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import ConditionVerdict, StreamTrigger, TriggerExecution
from agentarea_triggers.trigger_service import TriggerService


def _service(trigger: StreamTrigger) -> TriggerService:
    service = TriggerService(
        repository_factory=MagicMock(), event_broker=AsyncMock(), task_service=AsyncMock()
    )
    service.agent_repository = AsyncMock()
    service.agent_repository.get.return_value = SimpleNamespace(status="active")
    service.trigger_repository = AsyncMock()
    service.trigger_repository.get_trigger.return_value = trigger
    service.trigger_repository.disable_trigger.return_value = True
    service.trigger_execution_repository = AsyncMock()
    service.trigger_execution_repository.create.side_effect = lambda **kwargs: TriggerExecution(
        **kwargs
    )
    return service


def _trigger(**overrides) -> StreamTrigger:
    return StreamTrigger(
        **{
            "name": "t",
            "agent_id": uuid4(),
            "created_by": "u",
            "workspace_id": "w",
            "conditions": {"type": "llm", "description": "only invoices"},
            "failure_threshold": 5,
            **overrides,
        }
    )


def _counted_failures(service: TriggerService) -> list[int]:
    return [
        call.kwargs["consecutive_failures"]
        for call in service.trigger_repository.update_execution_tracking.await_args_list
    ]


async def test_five_filtered_events_in_a_row_do_not_disable_the_trigger():
    trigger = _trigger()
    tasks = AsyncMock()
    service = _service(trigger)
    service.task_service = tasks
    service.evaluate_trigger_verdict = AsyncMock(
        return_value=ConditionVerdict(verdict="not_met", reason="a greeting")
    )

    for _ in range(5):
        firing = await service.fire(trigger.id, {"text": "hi"})
        assert firing.outcome == "skipped"
        assert firing.execution is not None
        assert firing.execution.status == ExecutionStatus.SKIPPED

    service.trigger_repository.disable_trigger.assert_not_awaited()
    assert all(count == 0 for count in _counted_failures(service))
    assert trigger.consecutive_failures == 0
    tasks.route_or_submit_task.assert_not_awaited()


async def test_a_filtered_event_leaves_earlier_failures_counted():
    trigger = _trigger(consecutive_failures=3)
    service = _service(trigger)
    service.evaluate_trigger_verdict = AsyncMock(
        return_value=ConditionVerdict(verdict="not_met", reason="a greeting")
    )

    await service.fire(trigger.id, {"text": "hi"})

    assert trigger.consecutive_failures == 3
    assert all(count == 3 for count in _counted_failures(service))


async def test_an_inactive_trigger_records_its_turned_away_event_as_skipped():
    trigger = _trigger(is_active=False, conditions={})
    service = _service(trigger)

    firing = await service.fire(trigger.id, {"text": "hi"})

    assert firing.outcome == "skipped"
    assert firing.execution is not None
    assert firing.execution.status == ExecutionStatus.SKIPPED
    assert all(count == 0 for count in _counted_failures(service))
