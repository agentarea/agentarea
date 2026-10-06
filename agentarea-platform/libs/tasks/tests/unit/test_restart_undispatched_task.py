"""A task stored but never started is started on retry, under the policy stored with it, and only then."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.task_service import TaskService

POLICY = {"budget": {"run_budget_usd": "5.00"}}


def _service(engine) -> TaskService:
    factory = MagicMock()
    return TaskService(
        repository_factory=factory,
        event_broker=AsyncMock(),
        task_manager=engine,
        policy_resolver=AsyncMock(),
    )


def _stored(**overrides) -> AgentTask:
    base = {
        "id": uuid4(),
        "title": "Trigger: t",
        "description": "go",
        "query": "go",
        "user_id": "u",
        "workspace_id": "w",
        "agent_id": uuid4(),
        "status": "failed",
        "error_message": "temporal unavailable",
        "metadata": {"governance_snapshot": {"effective_policy": POLICY, "revision": 1}},
    }
    return AgentTask(**{**base, **overrides})


async def test_a_task_that_never_started_is_started_under_its_stored_policy():
    engine = MagicMock()
    engine.submit_task = AsyncMock(side_effect=lambda task: task)
    task = _stored()
    started = await _service(engine).restart_undispatched_task(task)
    submitted = engine.submit_task.await_args.args[0]
    assert submitted.id == task.id
    assert submitted.effective_policy == POLICY
    assert submitted.status == "pending"
    assert submitted.error_message is None
    assert started is submitted


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "running"},
        {"execution_id": "task-1"},
        {"metadata": {}},
    ],
)
async def test_a_task_that_started_or_has_no_policy_is_refused(overrides):
    engine = MagicMock()
    engine.submit_task = AsyncMock()
    with pytest.raises(ValueError):
        await _service(engine).restart_undispatched_task(_stored(**overrides))
    engine.submit_task.assert_not_awaited()


async def test_a_start_that_fails_again_raises():
    engine = MagicMock()
    engine.submit_task = AsyncMock(side_effect=ConnectionError("temporal unavailable"))
    with pytest.raises(ConnectionError):
        await _service(engine).restart_undispatched_task(_stored())
