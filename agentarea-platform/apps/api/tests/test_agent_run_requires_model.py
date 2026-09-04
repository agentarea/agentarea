"""API-level coverage for the "agent has no model" guard.

Catalog agents can be installed without a model when the workspace has no
matching instance (``model_id`` stays unset rather than pointing at a
non-existent model — see the catalog install resolution). Starting a run on
such an agent must fail fast at the API with a clear 422 / SSE error instead of
dispatching a doomed workflow.

These hit the real FastAPI app (routing, request parsing, the route's
exception handlers, response serialization) through ``httpx``/``ASGITransport``
with a *real* ``TaskService`` wired to mock repositories — so the guard actually
runs and the route's mapping to HTTP is exercised end-to-end, not mocked away.
"""

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


def _agent(*, model_id):
    agent = MagicMock(id=uuid4())
    agent.name = "Data Analyst"
    agent.model_id = model_id
    return agent


def _real_task_service(agent):
    """A genuine TaskService whose repositories are mocked; the guard runs for real."""
    task_repo = MagicMock()
    task_repo.create_task = AsyncMock(side_effect=lambda t: t)
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])

    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=agent)

    repo_factory = MagicMock()

    def create_repository(cls):
        if cls is TaskRepository:
            return task_repo
        if cls is AgentRepository:
            return agent_repo
        raise AssertionError(f"unexpected repository request: {cls}")

    repo_factory.create_repository = create_repository

    task_manager = MagicMock()

    async def _submit(t):
        t.status = "running"
        t.execution_id = f"task-{t.id}"
        return t

    task_manager.submit_task = AsyncMock(side_effect=_submit)
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
    # Short-circuit persistence (audit decorator + DB) — we test the route + guard.
    svc.create_task = AsyncMock(side_effect=lambda t: t)
    return svc, task_manager


@pytest.fixture
def wire():
    """Install dependency overrides for a given task/agent service, auto-cleaned."""

    def _wire(task_service, agent_service=None):
        app.dependency_overrides[get_user_context] = _user_context
        app.dependency_overrides[get_task_service] = lambda: task_service
        if agent_service is not None:
            app.dependency_overrides[get_agent_service] = lambda: agent_service

    yield _wire
    for dep in (get_user_context, get_task_service, get_agent_service):
        app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_sync_run_on_agent_without_model_returns_422(async_client, wire):
    svc, task_manager = _real_task_service(_agent(model_id=None))
    wire(svc)

    resp = await async_client.post(f"/v1/agents/{uuid4()}/tasks/sync", json={"description": "do x"})

    assert resp.status_code == 422
    assert resp.json()["detail"] == "Agent model is not configured"
    # The run must never reach Temporal dispatch.
    task_manager.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_run_with_model_override_succeeds(async_client, wire):
    # A model-less agent is still runnable when the caller supplies model_override.
    svc, task_manager = _real_task_service(_agent(model_id=None))
    wire(svc)

    resp = await async_client.post(
        f"/v1/agents/{uuid4()}/tasks/sync",
        json={"description": "do x", "parameters": {"model_override": "inst-1"}},
    )

    assert resp.status_code == 200
    task_manager.submit_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_run_on_agent_with_model_succeeds(async_client, wire):
    # Guard does not false-positive: an agent with a model runs normally.
    svc, task_manager = _real_task_service(_agent(model_id="inst-1"))
    wire(svc)

    resp = await async_client.post(f"/v1/agents/{uuid4()}/tasks/sync", json={"description": "do x"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    task_manager.submit_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_run_on_agent_without_model_emits_model_not_configured(async_client, wire):
    svc, task_manager = _real_task_service(_agent(model_id=None))
    agent_service = MagicMock()
    # The streaming endpoint verifies the agent exists via the catalog-aware getter.
    agent_service.get_with_catalog = AsyncMock(return_value=_agent(model_id=None))
    wire(svc, agent_service=agent_service)

    resp = await async_client.post(
        f"/v1/agents/{uuid4()}/tasks/",
        json={"description": "do x"},
    )

    assert resp.status_code == 200  # SSE stream opens, the error is an event in the body
    assert '"error_type": "model_not_configured"' in resp.text
    task_manager.submit_task.assert_not_awaited()
