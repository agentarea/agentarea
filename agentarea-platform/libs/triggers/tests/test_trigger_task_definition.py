"""A trigger that runs a saved task asks that task's text; one that does not, its own."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.task_definitions import TaskDefinition
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import (
    CronTrigger,
    StreamTrigger,
    TriggerCreate,
    TriggerExecution,
    TriggerUpdate,
)
from agentarea_triggers.trigger_service import TriggerService, TriggerValidationError

AGENT = uuid4()


def _definition(**overrides) -> TaskDefinition:
    now = datetime.now(UTC)
    return TaskDefinition(
        **{
            "id": uuid4(),
            "name": "Morning digest",
            "description": "Summarise yesterday's tickets",
            "agent_id": AGENT,
            "parameters": {"region": "eu"},
            "workspace_id": "w",
            "created_by": "u",
            "created_at": now,
            "updated_at": now,
            **overrides,
        }
    )


def _trigger(**overrides) -> StreamTrigger:
    return StreamTrigger(
        **{
            "name": "on ticket",
            "agent_id": AGENT,
            "created_by": "u",
            "workspace_id": "w",
            "task_parameters": {"text": "triage it", "priority": "high"},
            **overrides,
        }
    )


def _service(trigger=None, definition: TaskDefinition | None = None) -> TriggerService:
    service = TriggerService(
        repository_factory=MagicMock(),
        event_broker=AsyncMock(),
        task_service=AsyncMock(),
        temporal_schedule_manager=AsyncMock(),
    )
    service.trigger_repository = AsyncMock()
    service.trigger_repository.get_trigger.return_value = trigger
    service.trigger_execution_repository = AsyncMock()
    service.trigger_execution_repository.create.side_effect = lambda **kwargs: TriggerExecution(
        **kwargs
    )
    definitions = {definition.id: definition} if definition else {}
    service.task_definition_repository = AsyncMock()
    service.task_definition_repository.get_definition.side_effect = definitions.get
    service.agent_repository = AsyncMock()
    service.agent_repository.get.return_value = SimpleNamespace(id=AGENT, status="active")
    service.task_service.route_or_submit_task.side_effect = lambda task, **_: task
    return service


def _submitted(service: TriggerService):
    return service.task_service.route_or_submit_task.await_args.args[0]


async def test_a_trigger_on_a_saved_task_asks_its_text_and_records_it():
    definition = _definition()
    trigger = _trigger(task_definition_id=definition.id)
    service = _service(trigger, definition)

    firing = await service.fire(trigger.id, {})

    assert firing.outcome == "reacted"
    task = _submitted(service)
    assert task.description == "Summarise yesterday's tickets"
    assert task.query == "Summarise yesterday's tickets"
    assert task.task_parameters["region"] == "eu"
    assert "priority" not in task.task_parameters
    assert task.provenance.task_definition_id == definition.id
    assert task.provenance.origin_type == "trigger"
    assert task.provenance.origin_id == str(trigger.id)


async def test_a_trigger_without_a_saved_task_asks_its_own_text():
    trigger = _trigger()
    service = _service(trigger)

    await service.fire(trigger.id, {})

    task = _submitted(service)
    assert task.description == "triage it"
    assert task.task_parameters["priority"] == "high"
    assert task.provenance.task_definition_id is None
    assert task.provenance.origin_type == "trigger"
    assert task.provenance.origin_id == str(trigger.id)
    service.task_definition_repository.get_definition.assert_not_awaited()


async def test_a_trigger_whose_saved_task_is_gone_starts_nothing():
    trigger = _trigger(task_definition_id=uuid4())
    service = _service(trigger)

    firing = await service.fire(trigger.id, {})

    assert firing.outcome == "error"
    assert "no longer exists" in (firing.reason or "")
    service.task_service.route_or_submit_task.assert_not_awaited()


def _cron(**overrides) -> TriggerCreate:
    return TriggerCreate(
        **{
            "name": "daily",
            "agent_id": AGENT,
            "trigger_type": TriggerType.CRON,
            "cron_expression": "0 9 * * *",
            "created_by": "u",
            "workspace_id": "w",
            **overrides,
        }
    )


async def test_a_schedule_on_a_saved_task_needs_no_text_of_its_own():
    definition = _definition()
    service = _service(definition=definition)
    service.trigger_repository.create_from_model.side_effect = lambda data: CronTrigger(
        **data.model_dump(exclude={"stream_id", "event_filter", "session", "batch"})
    )

    trigger = await service.create_trigger(_cron(task_definition_id=definition.id))

    assert trigger.task_definition_id == definition.id


async def test_a_schedule_with_neither_text_nor_saved_task_is_refused():
    service = _service()

    with pytest.raises(TriggerValidationError, match="Task text"):
        await service.create_trigger(_cron())


@pytest.mark.parametrize(
    "definition, message",
    [(None, "does not exist"), (_definition(agent_id=uuid4()), "not the trigger's agent")],
)
async def test_a_trigger_runs_a_saved_task_of_its_workspace_and_its_agent(definition, message):
    service = _service(definition=definition)
    definition_id = definition.id if definition else uuid4()

    with pytest.raises(TriggerValidationError, match=message):
        await service.create_trigger(_cron(task_definition_id=definition_id))

    service.trigger_repository.create_from_model.assert_not_awaited()


async def test_pointing_a_trigger_at_another_agents_saved_task_is_refused():
    definition = _definition(agent_id=uuid4())
    service = _service(definition=definition)

    with pytest.raises(TriggerValidationError, match="not the trigger's agent"):
        await service._validate_trigger_update(
            _trigger(), TriggerUpdate(task_definition_id=definition.id)
        )
