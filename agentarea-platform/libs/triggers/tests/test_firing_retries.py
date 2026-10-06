"""On the stream path a firing retries what may pass and reports what will not.

The dispatcher still holds the event: a failure that a retry may not repeat
must raise so it backs off and tries again, and must not count towards the
trigger's failure threshold -- a short outage would otherwise switch it off.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import httpx
import pytest
from agentarea_llm.infrastructure.model_clients import (
    ModelCallError,
    ModelProviderUnavailableError,
)
from agentarea_triggers.domain.models import ConditionVerdict, WebhookTrigger
from agentarea_triggers.failures import TaskNotStartedError, is_permanent, is_transient
from agentarea_triggers.llm_condition_evaluator import LLMConditionEvaluationError
from agentarea_triggers.logging_utils import TriggerConditionError
from agentarea_triggers.trigger_service import TriggerService
from sqlalchemy.exc import IntegrityError, OperationalError
from temporalio.service import RPCError, RPCStatusCode


def _service(trigger: WebhookTrigger) -> TriggerService:
    service = TriggerService(repository_factory=MagicMock(), event_broker=AsyncMock())
    service.trigger_repository = AsyncMock()
    service.trigger_repository.get_trigger.return_value = trigger
    service.trigger_execution_repository = AsyncMock()
    service.task_service = AsyncMock()
    service.task_service.get_task.return_value = None
    service.disable_trigger = AsyncMock()
    return service


def _trigger(**overrides) -> WebhookTrigger:
    return WebhookTrigger(
        **{
            "name": "t",
            "agent_id": uuid4(),
            "created_by": "u",
            "workspace_id": "w",
            "webhook_id": "wh-1234567890abcd",
            "failure_threshold": 1,
            **overrides,
        }
    )


def _caused(error: Exception, cause: BaseException) -> Exception:
    error.__cause__ = cause
    return error


async def test_a_transient_failure_on_the_stream_path_raises_and_leaves_the_trigger_alone():
    trigger = _trigger()
    service = _service(trigger)
    service.task_service.route_or_submit_task.side_effect = OperationalError(
        "INSERT INTO tasks", {}, ConnectionResetError("reset")
    )
    with pytest.raises(OperationalError):
        await service.fire(trigger.id, {"text": "go"}, task_id=uuid4(), raise_retryable=True)
    service.trigger_execution_repository.create.assert_not_awaited()
    service.trigger_repository.update_execution_tracking.assert_not_awaited()
    service.disable_trigger.assert_not_awaited()
    assert trigger.is_active and trigger.consecutive_failures == 0


async def test_a_model_outage_behind_a_condition_error_is_retried():
    trigger = _trigger(conditions={"type": "llm", "description": "x", "model_id": str(uuid4())})
    service = _service(trigger)
    outage = _caused(
        TriggerConditionError("Trigger conditions could not be evaluated"),
        _caused(LLMConditionEvaluationError("LLM call failed"), httpx.ConnectError("refused")),
    )
    service.evaluate_trigger_verdict = AsyncMock(side_effect=outage)
    with pytest.raises(TriggerConditionError):
        await service.fire(trigger.id, {"text": "go"}, task_id=uuid4(), raise_retryable=True)
    service.disable_trigger.assert_not_awaited()


async def test_a_condition_nobody_can_decide_is_reported_as_an_error_outcome():
    trigger = _trigger(conditions={"type": "llm", "description": "x", "model_id": str(uuid4())})
    service = _service(trigger)
    service.evaluate_trigger_verdict = AsyncMock(
        side_effect=_caused(
            TriggerConditionError("Trigger conditions could not be evaluated"),
            LLMConditionEvaluationError("Decision model answered 'maybe'"),
        )
    )
    firing = await service.fire(trigger.id, {"text": "go"}, task_id=uuid4(), raise_retryable=True)
    assert firing.outcome == "error"


async def test_without_the_stream_path_every_failure_is_still_an_error_outcome():
    trigger = _trigger()
    service = _service(trigger)
    service.task_service.route_or_submit_task.side_effect = ConnectionResetError("reset")
    firing = await service.fire(trigger.id, {"text": "go"})
    assert firing.outcome == "error"


async def test_a_skipped_verdict_is_unchanged_by_the_stream_path():
    trigger = _trigger(conditions={"type": "llm", "description": "x", "model_id": str(uuid4())})
    service = _service(trigger)
    service.evaluate_trigger_verdict = AsyncMock(
        return_value=ConditionVerdict(verdict="not_met", reason="a greeting")
    )
    firing = await service.fire(trigger.id, {"text": "hi"}, raise_retryable=True)
    assert (firing.outcome, firing.reason) == ("skipped", "a greeting")


@pytest.mark.parametrize(
    "error",
    [
        ConnectionResetError("reset"),
        TimeoutError(),
        OperationalError("SELECT 1", {}, Exception("server closed the connection")),
        httpx.ReadTimeout("slow"),
        RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b""),
        _caused(ValueError("wrapped"), ConnectionResetError("reset")),
    ],
)
def test_infrastructure_trouble_is_transient(error):
    assert is_transient(error)
    assert not is_permanent(error)


@pytest.mark.parametrize(
    "error",
    [
        TriggerConditionError("no model_id"),
        LLMConditionEvaluationError("Unknown operator: ~"),
        ValueError("user_id is required to execute a task"),
    ],
)
def test_a_failure_that_repeats_on_every_retry_is_permanent(error):
    assert is_permanent(error)


@pytest.mark.parametrize(
    "error",
    [
        RPCError("bad", RPCStatusCode.INVALID_ARGUMENT, b""),
        IntegrityError("INSERT INTO tasks", {}, Exception("duplicate key")),
        RuntimeError("a bug"),
    ],
)
def test_an_unclassified_failure_is_neither_so_the_stream_path_retries_it(error):
    assert not is_transient(error)
    assert not is_permanent(error)


def _not_started(task_id):
    return SimpleNamespace(
        id=task_id,
        status="failed",
        execution_id=None,
        result={"error": "temporal unavailable", "error_type": "task_submission_failed"},
    )


async def test_a_task_stored_but_not_started_raises_on_the_stream_path():
    trigger = _trigger()
    service = _service(trigger)
    task_id = uuid4()
    service.task_service.route_or_submit_task.return_value = _not_started(task_id)
    with pytest.raises(TaskNotStartedError, match="temporal unavailable"):
        await service.fire(trigger.id, {"text": "go"}, task_id=task_id, raise_retryable=True)
    service.trigger_repository.update_execution_tracking.assert_not_awaited()
    service.disable_trigger.assert_not_awaited()


async def test_a_task_stored_but_not_started_is_unchanged_off_the_stream_path():
    trigger = _trigger()
    service = _service(trigger)
    service.task_service.route_or_submit_task.return_value = _not_started(uuid4())
    firing = await service.fire(trigger.id, {"text": "go"})
    assert firing.outcome == "reacted"


async def test_the_retry_starts_the_task_an_earlier_attempt_stored():
    trigger = _trigger()
    service = _service(trigger)
    task_id = uuid4()
    stored = _not_started(task_id)
    service.task_service.get_task.return_value = stored
    firing = await service.fire(trigger.id, {"text": "go"}, task_id=task_id, raise_retryable=True)
    service.task_service.restart_undispatched_task.assert_awaited_once_with(stored)
    service.task_service.route_or_submit_task.assert_not_awaited()
    assert (firing.outcome, firing.task_id) == ("reacted", task_id)


async def test_a_retry_that_still_cannot_start_the_task_raises():
    trigger = _trigger()
    service = _service(trigger)
    task_id = uuid4()
    service.task_service.get_task.return_value = _not_started(task_id)
    service.task_service.restart_undispatched_task.side_effect = RPCError(
        "unavailable", RPCStatusCode.UNAVAILABLE, b""
    )
    with pytest.raises(RPCError):
        await service.fire(trigger.id, {"text": "go"}, task_id=task_id, raise_retryable=True)


async def test_a_task_that_started_is_never_started_again():
    trigger = _trigger()
    service = _service(trigger)
    task_id = uuid4()
    service.task_service.get_task.return_value = SimpleNamespace(
        id=task_id, status="failed", execution_id="task-1", result=None
    )
    firing = await service.fire(trigger.id, {"text": "go"}, task_id=task_id, raise_retryable=True)
    service.task_service.restart_undispatched_task.assert_not_awaited()
    assert firing.outcome == "reacted"


def test_a_decision_provider_outage_behind_a_condition_error_is_transient():
    chain = _caused(
        TriggerConditionError("Trigger conditions could not be evaluated"),
        _caused(
            LLMConditionEvaluationError("Condition evaluation failed"),
            ModelProviderUnavailableError("decision failed with HTTP 503", status_code=503),
        ),
    )
    assert is_transient(chain)
    assert not is_permanent(chain)


def test_a_decision_the_provider_refused_behind_a_condition_error_is_permanent():
    chain = _caused(
        TriggerConditionError("Trigger conditions could not be evaluated"),
        _caused(
            LLMConditionEvaluationError("Condition evaluation failed"),
            ModelCallError("decision failed with HTTP 400"),
        ),
    )
    assert is_permanent(chain)


async def test_a_duplicate_task_from_a_concurrent_delivery_is_retried_not_counted():
    trigger = _trigger()
    service = _service(trigger)
    service.task_service.route_or_submit_task.side_effect = IntegrityError(
        "INSERT INTO tasks", {}, Exception("duplicate key value violates unique constraint")
    )
    with pytest.raises(IntegrityError):
        await service.fire(trigger.id, {"text": "go"}, task_id=uuid4(), raise_retryable=True)
    service.trigger_repository.update_execution_tracking.assert_not_awaited()
    service.disable_trigger.assert_not_awaited()


async def test_a_restarted_task_is_told_the_event_again():
    """The stored row keeps only the ask; the retry composes the full message again."""
    trigger = _trigger(task_parameters={"text": "Ship the order"})
    service = _service(trigger)
    task_id = uuid4()
    stored = _not_started(task_id)
    stored.query = "Ship the order"
    service.task_service.get_task.return_value = stored
    await service.fire(
        trigger.id, {"events": [{"order": "A-7"}]}, task_id=task_id, raise_retryable=True
    )
    assert stored.query.startswith("Ship the order\n\n## What started this run")
    assert '"order": "A-7"' in stored.query
