from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_streams.domain import StreamEvent
from agentarea_streams.domain.keys import task_id_for
from agentarea_triggers.batches import (
    batch_event,
    batch_task_id,
    batch_trigger_event,
    batch_workflow_id,
)
from agentarea_triggers.domain.models import StreamTrigger, TriggerBatchWindow
from agentarea_triggers.schemas.dto import TriggerCreate
from agentarea_triggers.trigger_service import compose_task_input
from pydantic import ValidationError


def _event(key: str, data: dict | None = None) -> StreamEvent:
    return StreamEvent(
        type="order.paid",
        source="webhook:shop",
        data=data or {"body": {"order": key}},
        stream_id=uuid4(),
        workspace_id="w",
        created_by="u",
        event_key=key,
        received_at=datetime(2026, 10, 19, 12, 0, tzinfo=UTC),
    )


def test_a_window_needs_a_time_or_a_count():
    with pytest.raises(ValidationError, match="window or max_events"):
        TriggerBatchWindow()
    assert TriggerBatchWindow(window="1h").max_events is None
    assert TriggerBatchWindow(max_events=3).window is None


@pytest.mark.parametrize("window", ["1", "1w", "-5m", "0s", "10 m"])
def test_a_window_is_a_positive_duration(window):
    with pytest.raises(ValidationError):
        TriggerBatchWindow(window=window)


def test_a_count_of_one_is_not_a_batch():
    with pytest.raises(ValidationError):
        TriggerBatchWindow(max_events=1)


def test_the_window_in_seconds():
    assert TriggerBatchWindow(window="2m").window_seconds() == 120
    assert TriggerBatchWindow(max_events=3).window_seconds() is None


def test_a_stream_trigger_dto_takes_a_batch_and_a_cron_one_refuses_it():
    created = TriggerCreate(
        name="t",
        agent_id=uuid4(),
        trigger_type="stream",
        stream_id=uuid4(),
        batch={"window": "60s", "max_events": 3},
    )
    assert created.to_domain("u").batch == TriggerBatchWindow(window="60s", max_events=3)
    with pytest.raises(ValidationError, match="only a stream trigger"):
        TriggerCreate(
            name="t",
            agent_id=uuid4(),
            trigger_type="cron",
            cron_expression="0 * * * *",
            batch={"window": "1h"},
        )


def test_one_open_batch_per_trigger_and_per_admitted_sender():
    trigger = uuid4()
    assert batch_workflow_id(trigger, None) == f"trigger-batch-{trigger}"
    assert batch_workflow_id(trigger, "alice") == batch_workflow_id(trigger, "alice")
    assert batch_workflow_id(trigger, "alice") != batch_workflow_id(trigger, "bob")
    assert batch_workflow_id(trigger, "alice").startswith(f"trigger-batch-{trigger}-")


def test_a_batch_task_is_named_by_its_first_event_and_never_by_a_single_firing():
    subscription, first = uuid4(), uuid4()
    assert batch_task_id(subscription, first) == batch_task_id(subscription, first)
    assert batch_task_id(subscription, first) != task_id_for(subscription, first)
    assert batch_task_id(subscription, first) != batch_task_id(subscription, uuid4())


def test_the_task_gets_its_ask_and_every_event_of_the_batch_in_one_block():
    trigger = StreamTrigger(
        name="digest",
        agent_id=uuid4(),
        created_by="u",
        task_parameters={"text": "Summarise these orders"},
        batch=TriggerBatchWindow(window="1h"),
    )
    first, second = _event("a"), _event("b")
    told = batch_trigger_event(
        [batch_event(first, {"order": "a"}), batch_event(second, {"order": "b"})],
        stream_name="orders",
    )
    assert told.stream_name == "orders"
    assert [e["key"] for e in told.data["events"]] == ["a", "b"]
    assert told.data["events"][0] == {
        "id": str(first.id),
        "kind": "order.paid",
        "key": "a",
        "received_at": "2026-10-19T12:00:00+00:00",
        "data": {"body": {"order": "a"}},
    }
    task_input = compose_task_input(trigger, told.data, told)
    assert task_input is not None
    assert task_input.ask == "Summarise these orders"
    assert task_input.message.startswith("Summarise these orders\n\n## What started this run")
    assert '"key": "b"' in task_input.message


def test_a_body_moved_to_files_is_read_back_into_its_event():
    event = _event("a", {"body": None, "body_ref": "events/a.json", "headers": {}})
    entry = batch_event(event, {"order": "a"})
    assert entry["data"]["body"] == {"order": "a"}
    assert entry["data"]["body_ref"] == "events/a.json"


def _service():
    from unittest.mock import AsyncMock, MagicMock

    from agentarea_triggers.trigger_service import TriggerService

    from .conftest import make_trigger_repository_factory

    service = TriggerService(
        repository_factory=make_trigger_repository_factory(), event_broker=AsyncMock()
    )
    service.stream_service = MagicMock()
    service.stream_service.get_stream = AsyncMock()
    return service


def _create(batch: TriggerBatchWindow, text: str | None = "Summarise"):
    from agentarea_triggers.domain.enums import TriggerType
    from agentarea_triggers.domain.models import TriggerCreate as DomainCreate

    return DomainCreate(
        name="t",
        agent_id=uuid4(),
        trigger_type=TriggerType.STREAM,
        stream_id=uuid4(),
        created_by="u",
        task_parameters={"text": text} if text else {},
        batch=batch,
    )


async def test_a_count_above_the_deployment_cap_is_refused():
    from agentarea_triggers.trigger_service import TriggerValidationError

    with pytest.raises(TriggerValidationError, match="at most 100 events"):
        await _service().validate_configuration(_create(TriggerBatchWindow(max_events=101)))
    await _service().validate_configuration(_create(TriggerBatchWindow(max_events=100)))


async def test_a_batch_needs_task_text_to_say_what_to_do_with_its_events():
    from agentarea_triggers.trigger_service import TriggerValidationError

    with pytest.raises(TriggerValidationError, match="needs task text"):
        await _service().validate_configuration(_create(TriggerBatchWindow(window="1h"), None))
