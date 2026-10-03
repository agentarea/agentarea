"""Run creation refused by the workspace monthly spend cap says so.

Each creation route maps the refusal: ``/sync`` and ``/schedule`` answer the
402 problem the app registers for the cap, the streaming route emits an
``error`` event with ``monthly_spend_cap_exceeded`` and the amounts. A real
``TaskService`` with mocked repositories runs the cap check, so the route's
mapping is exercised end-to-end.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
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

_CAP = Decimal("0.000001")
_SPENT = Decimal("0.000058")


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
    agent.name = "Capped Agent"
    agent.model_id = "inst-1"
    return agent


def _capped_task_service():
    task_repo = MagicMock()
    task_repo.create_task = AsyncMock(side_effect=lambda t: t)
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])
    task_repo.sum_spend_mtd = AsyncMock(return_value=_SPENT)

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

    task_manager = MagicMock()
    task_manager.submit_task = AsyncMock()
    task_manager.temporal_executor = None

    policy_resolver = MagicMock()
    policy_resolver.resolve = AsyncMock(
        return_value=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd=Decimal("1.00"), monthly_spend_cap_usd=_CAP),
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
def capped(async_client):
    svc, task_manager = _capped_task_service()
    agent_service = MagicMock()
    agent_service.get_with_catalog = AsyncMock(return_value=_agent())
    app.dependency_overrides[get_user_context] = _user_context
    app.dependency_overrides[get_task_service] = lambda: svc
    app.dependency_overrides[get_agent_service] = lambda: agent_service
    yield task_manager
    for dep in (get_user_context, get_task_service, get_agent_service):
        app.dependency_overrides.pop(dep, None)


def _assert_cap_problem(resp) -> None:
    assert resp.status_code == 402
    body = resp.json()
    assert body["code"] == "budget_cap_exceeded"
    assert body["current_mtd_usd"] == pytest.approx(0.000058)
    assert body["cap_usd"] == pytest.approx(0.000001)
    assert body["currency"] == "USD"
    assert "0.000058 USD" in body["detail"]
    assert "0.000001 USD" in body["detail"]


@pytest.mark.asyncio
async def test_sync_run_over_the_monthly_cap_is_402(async_client, capped):
    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/sync", json={"description": "do x"}
    )

    _assert_cap_problem(resp)
    capped.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduled_run_over_the_monthly_cap_is_402(async_client, capped):
    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/schedule",
        json={
            "description": "do x",
            "scheduled_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )

    _assert_cap_problem(resp)
    capped.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_streamed_run_over_the_monthly_cap_emits_the_cap_error(async_client, capped):
    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/", json={"description": "do x"}
    )

    assert resp.status_code == 200  # SSE stream opens, the refusal is an event in the body
    errors = [
        json.loads(line.removeprefix("data: "))
        for block in resp.text.split("\n\n")
        if block.startswith("event: error")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    assert len(errors) == 1
    error = errors[0]
    assert error["error_type"] == "monthly_spend_cap_exceeded"
    assert error["current_mtd_usd"] == pytest.approx(0.000058)
    assert error["cap_usd"] == pytest.approx(0.000001)
    assert error["currency"] == "USD"
    assert "0.000058 USD/0.000001 USD" in error["error"]
    capped.submit_task.assert_not_awaited()
