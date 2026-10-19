"""A spend cap or budget turning a firing away is not the trigger failing."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.exceptions import BudgetCapExceededError
from agentarea_tasks.model_spend_caps import SpendCapReachedError
from agentarea_triggers.domain.enums import ExecutionStatus
from agentarea_triggers.domain.models import StreamTrigger, TriggerExecution
from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluationError
from agentarea_triggers.trigger_service import TriggerService


def _service(trigger: StreamTrigger) -> TriggerService:
    service = TriggerService(
        repository_factory=MagicMock(), event_broker=AsyncMock(), task_service=AsyncMock()
    )
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
            "task_parameters": {"text": "handle it"},
            "failure_threshold": 5,
            **overrides,
        }
    )


def _condition_refused() -> Exception:
    try:
        try:
            raise SpendCapReachedError("Workspace monthly spend cap reached (3.5 RUB/0.01 RUB)")
        except SpendCapReachedError as refused:
            raise LLMConditionEvaluationError(f"model call refused: {refused}") from refused
    except LLMConditionEvaluationError as error:
        return error


@pytest.mark.parametrize("raise_retryable", [False, True])
async def test_submission_refused_by_the_monthly_cap_never_disables_the_trigger(raise_retryable):
    trigger = _trigger()
    service = _service(trigger)
    service.task_service.route_or_submit_task.side_effect = BudgetCapExceededError(
        workspace_id="w", current_mtd_usd=Decimal("3.5"), cap_usd=Decimal("0.01")
    )

    for _ in range(6):
        firing = await service.fire(trigger.id, {"text": "hi"}, raise_retryable=raise_retryable)
        assert firing.outcome == "skipped"
        assert firing.execution is not None
        assert firing.execution.status == ExecutionStatus.SKIPPED

    service.trigger_repository.disable_trigger.assert_not_awaited()
    assert trigger.consecutive_failures == 0
    assert trigger.is_active


async def test_llm_condition_refused_by_a_spend_cap_never_disables_the_trigger():
    trigger = _trigger(conditions={"type": "llm", "description": "only invoices"})
    service = _service(trigger)
    service.evaluate_trigger_verdict = AsyncMock(side_effect=_condition_refused())

    for _ in range(6):
        firing = await service.fire(trigger.id, {"text": "hi"})
        assert firing.outcome == "skipped"
        assert "spend cap" in (firing.reason or "")

    service.trigger_repository.disable_trigger.assert_not_awaited()
    assert trigger.consecutive_failures == 0
    service.task_service.route_or_submit_task.assert_not_awaited()


async def test_a_refusal_leaves_earlier_failures_counted():
    trigger = _trigger(consecutive_failures=3)
    service = _service(trigger)
    service.task_service.route_or_submit_task.side_effect = BudgetCapExceededError(
        workspace_id="w", current_mtd_usd=Decimal("3.5"), cap_usd=Decimal("0.01")
    )

    await service.fire(trigger.id, {"text": "hi"})

    assert trigger.consecutive_failures == 3
