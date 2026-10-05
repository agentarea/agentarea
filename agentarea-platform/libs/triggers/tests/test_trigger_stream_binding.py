from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus, TriggerType
from agentarea_triggers.domain.models import (
    ConditionVerdict,
    TriggerCreate,
    TriggerExecution,
    WebhookTrigger,
)
from agentarea_triggers.logging_utils import TriggerConditionError, TriggerValidationError
from agentarea_triggers.schemas.dto import TriggerCreate as TriggerCreatePayload
from agentarea_triggers.trigger_service import TriggerService


def _service() -> TriggerService:
    factory = MagicMock()
    service = TriggerService(repository_factory=factory, event_broker=AsyncMock())
    service.trigger_repository = AsyncMock()
    service.trigger_repository.webhook_id_in_use.return_value = False
    service.trigger_execution_repository = AsyncMock()
    service.agent_repository = AsyncMock()
    service.model_instance_repository = AsyncMock()
    service.stream_service = AsyncMock()
    return service


def test_the_dto_accepts_a_stream_trigger_and_requires_its_stream():
    agent = uuid4()
    with pytest.raises(ValueError, match="stream_id is required"):
        TriggerCreatePayload(name="n", trigger_type="stream", agent_id=agent)
    payload = TriggerCreatePayload(
        name="n",
        trigger_type="stream",
        agent_id=agent,
        stream_id=uuid4(),
        event_filter={"kinds": ["push"]},
    )
    domain = payload.to_domain(created_by="u", workspace_id="w")
    assert domain.trigger_type == TriggerType.STREAM
    assert domain.event_filter == {"kinds": ["push"]}


async def test_a_webhook_trigger_gets_its_own_stream_source_and_subscription(monkeypatch):
    monkeypatch.setattr(
        "agentarea_triggers.trigger_service.find_webhook_source", AsyncMock(return_value=None)
    )
    service = _service()
    trigger = WebhookTrigger(
        name="gh",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        webhook_id="wh-1234567890abcd",
        webhook_type="github",
        event_types=["push"],
    )
    service.trigger_repository.create_from_model.return_value = trigger
    await service.create_trigger(
        TriggerCreate(
            name="gh",
            agent_id=trigger.agent_id,
            trigger_type=TriggerType.WEBHOOK,
            created_by="u",
            webhook_id=trigger.webhook_id,
            webhook_type="github",
            event_types=["push"],
        )
    )
    kwargs = service.stream_service.create_webhook_stream_for_trigger.await_args.kwargs
    assert kwargs["trigger_id"] == trigger.id
    assert kwargs["webhook_id"] == "wh-1234567890abcd"
    assert kwargs["event_types"] == ["push"]


async def test_a_stream_trigger_subscribes_to_the_stream_it_names():
    service = _service()
    stream_id = uuid4()
    created = SimpleNamespace(
        id=uuid4(), name="s", agent_id=uuid4(), trigger_type=TriggerType.STREAM
    )
    service.trigger_repository.create_from_model.return_value = created
    await service.create_trigger(
        TriggerCreate(
            name="s",
            agent_id=created.agent_id,
            trigger_type=TriggerType.STREAM,
            created_by="u",
            stream_id=stream_id,
            event_filter={"kinds": ["a"]},
        )
    )
    kwargs = service.stream_service.subscribe_trigger.await_args.kwargs
    assert kwargs["stream_id"] == stream_id
    assert kwargs["event_filter"].kinds == ["a"]


async def test_a_stream_trigger_on_a_foreign_stream_is_refused():
    from agentarea_streams.domain import StreamNotFoundError

    service = _service()
    service.stream_service.get_stream.side_effect = StreamNotFoundError(uuid4())
    with pytest.raises(TriggerValidationError, match="Stream"):
        await service._validate_trigger_configuration(
            TriggerCreate(
                name="s",
                agent_id=uuid4(),
                trigger_type=TriggerType.STREAM,
                created_by="u",
                stream_id=uuid4(),
            )
        )


def _trigger(**overrides):
    base = dict(
        name="t",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="w",
        webhook_id="wh-1234567890abcd",
        conditions={"type": "llm", "description": "x", "model_id": str(uuid4())},
    )
    return WebhookTrigger(**{**base, **overrides})


def _execution(status=ExecutionStatus.FAILED, message=None, task_id=None):
    return TriggerExecution(
        trigger_id=uuid4(),
        status=status,
        execution_time_ms=0,
        error_message=message,
        task_id=task_id,
    )


async def test_fire_reports_skipped_with_the_verdict_reason():
    service = _service()
    trigger = _trigger()
    service.trigger_repository.get_trigger.return_value = trigger
    service.evaluate_trigger_verdict = AsyncMock(
        return_value=ConditionVerdict(verdict="not_met", score=0.2, reason="a greeting")
    )
    service.record_execution = AsyncMock(return_value=_execution())
    firing = await service.fire(trigger.id, {"text": "hi"})
    assert firing.outcome == "skipped"
    assert firing.reason == "a greeting"
    assert firing.verdict and firing.verdict.score == 0.2


async def test_fire_reports_an_undecidable_condition_as_an_error():
    service = _service()
    trigger = _trigger()
    service.trigger_repository.get_trigger.return_value = trigger
    service.evaluate_trigger_verdict = AsyncMock(side_effect=TriggerConditionError("model down"))
    service.record_execution = AsyncMock(return_value=_execution())
    firing = await service.fire(trigger.id, {"text": "hi"})
    assert firing.outcome == "error"
    assert "model down" in (firing.reason or "")


async def test_fire_reuses_a_task_already_created_for_this_event():
    service = _service()
    trigger = _trigger(conditions={})
    service.trigger_repository.get_trigger.return_value = trigger
    task_id = uuid4()
    service.task_service = AsyncMock()
    service.task_service.get_task.return_value = SimpleNamespace(id=task_id)
    firing = await service.fire(trigger.id, {"text": "go"}, task_id=task_id)
    assert (firing.outcome, firing.task_id) == ("reacted", task_id)
    service.task_service.route_or_submit_task.assert_not_awaited()


async def test_fire_creates_the_task_with_the_given_id_and_provenance():
    from agentarea_tasks.domain.models import TaskProvenance

    service = _service()
    trigger = _trigger(conditions={})
    service.trigger_repository.get_trigger.return_value = trigger
    task_id = uuid4()
    service.task_service = AsyncMock()
    service.task_service.get_task.return_value = None
    service.task_service.route_or_submit_task.return_value = SimpleNamespace(
        id=task_id, status="pending"
    )
    service.record_execution = AsyncMock(
        return_value=_execution(ExecutionStatus.SUCCESS, task_id=task_id)
    )
    provenance = TaskProvenance(origin_type="trigger", origin_id=str(trigger.id), causation_id="evt")
    firing = await service.fire(trigger.id, {"text": "go"}, task_id=task_id, provenance=provenance)
    submitted = service.task_service.route_or_submit_task.await_args.args[0]
    assert submitted.id == task_id
    assert submitted.provenance == provenance
    assert firing.outcome == "reacted"
