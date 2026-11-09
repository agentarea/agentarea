"""A run started over the API may name the runner client it runs on.

Real FastAPI app and a real ``TaskService`` over mocked repositories, so the
request field, the service's client check and the route's error mapping all run.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_api.api.deps.services import get_agent_service, get_task_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container
from agentarea_execution.models import RUNNER_CLIENT_METADATA_KEY
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.client_repository import ClientRepository
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService
from httpx import ASGITransport, AsyncClient


class _Allow(PermissionService):
    async def check(self, subject, permission, resource_type, resource_id) -> bool:
        return True


@pytest.fixture(autouse=True)
def permissions():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(PermissionService, _Allow())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


@pytest_asyncio.fixture
async def async_client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _user_context():
    ctx = MagicMock()
    ctx.user_id = "test_user"
    ctx.workspace_id = "test_workspace"
    return ctx


def _agent():
    agent = MagicMock(id=uuid4(), model_id="inst-1", client_id=None)
    agent.name = "Data Analyst"
    return agent


def _service_with_clients(clients: dict):
    """A real TaskService over mocked repositories that knows these clients."""
    task_repo = MagicMock()
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])
    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=_agent())
    client_repo = MagicMock()
    client_repo.get_by_id = AsyncMock(side_effect=lambda client_id: clients.get(client_id))
    repositories = {
        TaskRepository: task_repo,
        AgentRepository: agent_repo,
        ClientRepository: client_repo,
    }
    repo_factory = MagicMock()
    repo_factory.create_repository = lambda cls: repositories[cls]

    async def _submit(task):
        task.status = "running"
        task.execution_id = f"task-{task.id}"
        return task

    task_manager = MagicMock()
    task_manager.submit_task = AsyncMock(side_effect=_submit)
    task_manager.temporal_executor = None
    policy_resolver = MagicMock()
    policy_resolver.resolve = AsyncMock(
        return_value=EffectivePolicy(
            budget=BudgetPolicy(run_budget_usd="1.00"),
            tokens=TokenPolicy(max_tokens=1000, max_tokens_per_call=100),
            execution=ExecutionLimitsPolicy(
                max_model_turns=10, max_tool_calls_per_turn=10, max_tool_calls_total=100
            ),
        )
    )
    svc = TaskService(
        repository_factory=repo_factory,
        event_broker=AsyncMock(),
        task_manager=task_manager,
        policy_resolver=policy_resolver,
    )
    svc.create_task = AsyncMock(side_effect=lambda task: task)
    return svc, task_manager


@pytest.fixture
def wire():
    def _wire(task_service):
        agent_service = MagicMock()
        agent_service.get_with_catalog = AsyncMock(return_value=_agent())
        app.dependency_overrides[get_user_context] = _user_context
        app.dependency_overrides[get_task_service] = lambda: task_service
        app.dependency_overrides[get_agent_service] = lambda: agent_service

    yield _wire
    for dep in (get_user_context, get_task_service, get_agent_service):
        app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_a_run_named_onto_a_codex_client_runs_there(async_client, wire):
    runner = uuid4()
    svc, task_manager = _service_with_clients(
        {runner: MagicMock(spec=Client, id=runner, kind="codex")}
    )
    wire(svc)

    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/sync",
        json={"description": "do x", "runner_client_id": str(runner)},
    )

    assert resp.status_code == 200
    submitted = task_manager.submit_task.await_args.args[0]
    assert submitted.metadata[RUNNER_CLIENT_METADATA_KEY] == str(runner)


@pytest.mark.asyncio
async def test_a_client_that_runs_no_agents_is_refused(async_client, wire):
    harness = uuid4()
    svc, task_manager = _service_with_clients(
        {harness: MagicMock(spec=Client, id=harness, kind="harness")}
    )
    wire(svc)

    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/sync",
        json={"description": "do x", "runner_client_id": str(harness)},
    )

    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_runner_client_id"
    task_manager.submit_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_the_stream_reports_a_refused_client_as_its_own_error(async_client, wire):
    svc, task_manager = _service_with_clients({})
    wire(svc)

    resp = await async_client.post(
        f"/v1/workspaces/acme/agents/{uuid4()}/tasks/",
        json={"description": "do x", "runner_client_id": str(uuid4())},
    )

    assert '"error_type": "invalid_runner_client"' in resp.text
    task_manager.submit_task.assert_not_awaited()
