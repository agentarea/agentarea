"""API-level coverage for one-shot scheduled runs.

Hits the real FastAPI app through ``httpx``/``ASGITransport`` with a genuine
``TaskService`` over mock repositories, so request validation, the route's
exception mapping, and the ``scheduled_at`` hand-off to the task manager are
all exercised for real.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_api.api.deps.services import get_agent_service, get_task_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _user_context():
    ctx = MagicMock()
    ctx.user_id = "test_user"
    ctx.workspace_id = "test_workspace"
    return ctx


def _agent():
    agent = MagicMock(id=uuid4())
    agent.name = "Reminder Bot"
    agent.model_id = "inst-1"
    return agent


def _real_task_service(*, supports_scheduling=True):
    task_repo = MagicMock()
    task_repo.create_task = AsyncMock(side_effect=lambda t: t)
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])

    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=_agent())

    repo_factory = MagicMock()

    def create_repository(cls):
        if cls is TaskRepository:
            return task_repo
        if cls is AgentRepository:
            return agent_repo
        raise AssertionError(f"unexpected repository request: {cls}")

    repo_factory.create_repository = create_repository

    async def _submit(t):
        t.status = "scheduled" if t.scheduled_at else "running"
        t.execution_id = f"task-{t.id}"
        return t

    task_manager = MagicMock()
    task_manager.submit_task = AsyncMock(side_effect=_submit)
    task_manager.supports_scheduling = supports_scheduling
    task_manager.temporal_executor = None

    policy_resolver = MagicMock()
    policy_resolver.resolve = AsyncMock(
        return_value=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd="1.00"),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=10,
                max_tool_calls_per_turn=10,
                max_tool_calls_total=100,
            ),
        )
    )

    svc = TaskService(
        repository_factory=repo_factory,
        event_broker=AsyncMock(),
        task_manager=task_manager,
        policy_resolver=policy_resolver,
    )
    svc.create_task = AsyncMock(side_effect=lambda t: t)
    return svc, task_manager


@pytest.fixture
def wire():
    def _wire(task_service):
        app.dependency_overrides[get_user_context] = _user_context
        app.dependency_overrides[get_task_service] = lambda: task_service

    yield _wire
    for dep in (get_user_context, get_task_service, get_agent_service):
        app.dependency_overrides.pop(dep, None)


async def _schedule(client, when, description="send the report"):
    return await client.post(
        f"/v1/agents/{uuid4()}/tasks/schedule",
        json={"description": description, "scheduled_at": when},
    )


@pytest.mark.asyncio
async def test_scheduling_a_run_defers_it(async_client, wire):
    svc, task_manager = _real_task_service()
    wire(svc)
    when = datetime.now(UTC) + timedelta(days=1)

    resp = await _schedule(async_client, when.isoformat())

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "scheduled"
    assert datetime.fromisoformat(body["scheduled_at"]) == when
    # The moment must reach the manager, which is what turns it into a delay.
    submitted = task_manager.submit_task.await_args.args[0]
    assert submitted.scheduled_at == when


@pytest.mark.asyncio
async def test_naive_time_is_rejected(async_client, wire):
    svc, task_manager = _real_task_service()
    wire(svc)

    resp = await _schedule(async_client, "2030-01-01T09:00:00")

    assert resp.status_code == 422
    task_manager.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_past_time_is_rejected(async_client, wire):
    svc, task_manager = _real_task_service()
    wire(svc)
    when = datetime.now(UTC) - timedelta(minutes=1)

    resp = await _schedule(async_client, when.isoformat())

    assert resp.status_code == 422
    task_manager.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_engine_without_timers_reports_not_implemented(async_client, wire):
    """An engine with no durable timer must refuse, not run the task now."""
    svc, task_manager = _real_task_service(supports_scheduling=False)
    wire(svc)
    when = datetime.now(UTC) + timedelta(hours=2)

    resp = await _schedule(async_client, when.isoformat())

    assert resp.status_code == 501
    task_manager.submit_task.assert_not_awaited()
