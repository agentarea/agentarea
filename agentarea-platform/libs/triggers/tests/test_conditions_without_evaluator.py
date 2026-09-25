"""A path with no condition evaluator does not fire on conditions it cannot read.

The worker's trigger activity and the inbound channel consumer build a
TriggerService without an LLM evaluator, and the rule-based fallback reported
every condition other than field_matches as met, so rule and LLM conditions
fired on every event there.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import WebhookTrigger
from agentarea_triggers.logging_utils import TriggerConditionError
from agentarea_triggers.trigger_service import TriggerService

from .conftest import make_trigger_repository_factory


def _trigger(conditions):
    return WebhookTrigger(
        id=uuid4(),
        name="Urgent tickets",
        agent_id=uuid4(),
        webhook_id="webhook_urgent",
        conditions=conditions,
        task_parameters={"text": "Triage the ticket"},
        created_by="test_user",
    )


def _service(trigger_repo=None, execution_repo=None, task_service=None) -> TriggerService:
    return TriggerService(
        repository_factory=make_trigger_repository_factory(
            trigger_repo=trigger_repo or AsyncMock(),
            execution_repo=execution_repo or AsyncMock(),
            agent_repo=AsyncMock(),
        ),
        event_broker=AsyncMock(),
        task_service=task_service or AsyncMock(),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "conditions",
    [
        {"type": "rule", "rules": [{"field": "priority", "operator": "eq", "value": "high"}]},
        {"type": "llm", "description": "only urgent tickets"},
        {"field_matches": {"priority": "high"}, "type": "combined"},
    ],
)
async def test_a_condition_it_cannot_read_raises(conditions):
    with pytest.raises(TriggerConditionError):
        await _service().evaluate_trigger_conditions(_trigger(conditions), {"priority": "low"})


@pytest.mark.asyncio
async def test_field_matches_is_still_evaluated():
    service = _service()
    trigger = _trigger({"field_matches": {"priority": "high"}})

    assert await service.evaluate_trigger_conditions(trigger, {"priority": "high"}) is True
    assert await service.evaluate_trigger_conditions(trigger, {"priority": "low"}) is False


@pytest.mark.asyncio
async def test_execute_trigger_records_a_failed_run_and_creates_no_task():
    trigger = _trigger({"type": "llm", "description": "only urgent tickets"})
    trigger_repo = AsyncMock()
    trigger_repo.get_trigger.return_value = trigger
    execution_repo = AsyncMock()
    execution_repo.create.return_value = MagicMock(
        id=uuid4(), trigger_id=trigger.id, status=ExecutionStatus.FAILED
    )
    task_service = AsyncMock()

    await _service(trigger_repo, execution_repo, task_service).execute_trigger(
        trigger.id, {"events": [{"text": "ticket #1 opened"}]}
    )

    task_service.route_or_submit_task.assert_not_called()
    recorded = execution_repo.create.call_args.kwargs
    assert recorded["status"] == ExecutionStatus.FAILED.value


@pytest.mark.parametrize(("enabled", "expected"), [("true", True), ("false", False)])
def test_background_paths_get_the_evaluator_when_llm_conditions_are_enabled(
    monkeypatch, enabled, expected
):
    from agentarea_common.config import get_settings
    from agentarea_triggers.llm_condition_evaluator import (
        LLMConditionEvaluator,
        build_condition_evaluator,
    )

    monkeypatch.setenv("TRIGGER_ENABLE_LLM_CONDITIONS", enabled)
    get_settings.cache_clear()
    try:
        evaluator = build_condition_evaluator(
            session=MagicMock(),
            user_context=MagicMock(workspace_id="ws", user_id="u"),
            secret_manager=MagicMock(),
            event_broker=AsyncMock(),
        )
    finally:
        get_settings.cache_clear()

    assert isinstance(evaluator, LLMConditionEvaluator) is expected
