"""An update the trigger cannot take is refused as a validation error, and stays in its workspace."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.domain.models import CronTrigger, Trigger, TriggerUpdate, WebhookTrigger
from agentarea_triggers.infrastructure.repository import TriggerRepository
from agentarea_triggers.logging_utils import TriggerValidationError
from agentarea_triggers.trigger_service import TriggerService


def _service(existing: Trigger) -> TriggerService:
    service = TriggerService(repository_factory=MagicMock(), event_broker=AsyncMock())
    service.trigger_repository = AsyncMock()
    service.trigger_repository.get_trigger.return_value = existing
    service.stream_service = AsyncMock()
    service.model_instance_repository = AsyncMock()
    return service


def _webhook() -> WebhookTrigger:
    return WebhookTrigger(
        name="w",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="ws",
        webhook_id="wh-1234567890abcd",
    )


def _stream() -> Trigger:
    return Trigger(
        name="s",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="ws",
        trigger_type=TriggerType.STREAM,
    )


def _cron() -> CronTrigger:
    return CronTrigger(
        name="c",
        agent_id=uuid4(),
        created_by="u",
        workspace_id="ws",
        cron_expression="0 * * * *",
        task_parameters={"text": "go"},
    )


@pytest.mark.parametrize(
    ("existing", "update", "message"),
    [
        (_stream(), TriggerUpdate(event_filter={"kinds": "push"}), "event_filter"),
        (_stream(), TriggerUpdate(event_filter={"unknown": 1}), "event_filter"),
        (_cron(), TriggerUpdate(event_filter={"kinds": ["push"]}), "webhook and stream"),
        (
            _webhook(),
            TriggerUpdate(event_types=["push"], event_filter={"kinds": ["push"]}),
            "not both",
        ),
    ],
)
async def test_an_event_filter_the_trigger_cannot_take_is_refused_before_anything_changes(
    existing, update, message
):
    service = _service(existing)
    with pytest.raises(TriggerValidationError, match=message):
        await service.update_trigger(existing.id, update)
    service.trigger_repository.update_by_id.assert_not_awaited()
    service.stream_service.update_trigger_filter.assert_not_awaited()


async def test_a_valid_event_filter_reaches_the_subscription():
    existing = _stream()
    service = _service(existing)
    service.trigger_repository.update_by_id.return_value = existing
    await service.update_trigger(existing.id, TriggerUpdate(event_filter={"kinds": ["push"]}))
    [(trigger_id, event_filter)] = [
        call.args for call in service.stream_service.update_trigger_filter.await_args_list
    ]
    assert (trigger_id, event_filter.kinds) == (existing.id, ["push"])


async def test_an_update_is_confined_to_the_callers_workspace():
    session = AsyncMock()
    repository = TriggerRepository(session, UserContext(user_id="u", workspace_id="ws-a"))
    repository.get_trigger = AsyncMock(return_value=None)
    await repository.update_by_id(uuid4(), TriggerUpdate(name="renamed"))
    statement = session.execute.await_args.args[0]
    compiled = statement.compile()
    assert "triggers.workspace_id" in str(compiled)
    assert "ws-a" in compiled.params.values()
