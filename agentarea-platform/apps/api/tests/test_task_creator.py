"""A task must say who started it.

The `Source` badge answers *what* started a task (trigger, channel, delegation)
and falls through to "Manual" when nothing automated matched. That is not the
same question as *who*: a webhook-fired task is still owned by whoever created
the trigger. Both facts are recorded -- `tasks.created_by` has always held the
author -- but the read models dropped it, so the UI could not show it.

The id is all a task carries. Turning it into a name is GET /v1/workspaces/acme/principals'
job (see test_principals_api): the name belongs to a resource with a different
rate of change, and a task must not fail to load because the identity provider
is slow.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.agents_tasks import TaskResponse, TaskWithAgent
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_tasks.domain.models import AgentTask, Task
from httpx import ASGITransport, AsyncClient

CREATOR_ID = "bb206374-f612-420d-acd0-b62051061c63"


def _agent_task(user_id: str = CREATOR_ID) -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="task",
        description="do the thing",
        query="do the thing",
        user_id=user_id,
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="completed",
    )


def _task(user_id: str | None = CREATOR_ID) -> Task:
    return Task(
        id=uuid4(),
        agent_id=uuid4(),
        description="do the thing",
        parameters={},
        status="completed",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        user_id=user_id,
    )


def test_created_by_survives_the_agent_task_conversion() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    assert response.created_by == CREATOR_ID


def test_created_by_survives_the_task_with_agent_conversion() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    with_agent = TaskWithAgent.from_task_response(response, "neuresearch")

    assert with_agent.created_by == CREATOR_ID


def test_a_task_carries_no_resolved_name() -> None:
    """The read model holds the id and nothing derived from another system."""
    response = TaskResponse.from_agent_task(_agent_task())

    fields = TaskWithAgent.from_task_response(response, "neuresearch").model_dump()

    assert "created_by" in fields
    assert "created_by_name" not in fields


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
def task_endpoint_overrides():
    """Wire the read services the task endpoints depend on."""
    task = _task()

    task_service = AsyncMock()
    task_service.task_repository.get_by_id = AsyncMock(return_value=object())
    task_service.task_repository.list_page = AsyncMock(return_value=[object()])
    task_service.task_repository._orm_to_domain = MagicMock(return_value=task)

    agent = MagicMock()
    agent.id = task.agent_id
    agent.name = "SEO"
    agent_service = AsyncMock()
    agent_service.get_with_catalog.return_value = agent
    agent_service.list.return_value = [agent]

    user_context = MagicMock()
    user_context.user_id = CREATOR_ID
    user_context.workspace_id = "workspace-1"

    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_read_agent_service] = lambda: agent_service
    app.dependency_overrides[get_user_context] = lambda: user_context
    try:
        yield task
    finally:
        for dep in (get_read_task_service, get_read_agent_service, get_user_context):
            app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_the_task_list_endpoint_reports_who_started_each_task(
    async_client, task_endpoint_overrides
) -> None:
    response = await async_client.get("/v1/workspaces/acme/tasks/")

    assert response.status_code == 200, response.text
    assert response.json()[0]["created_by"] == CREATOR_ID


@pytest.mark.asyncio
async def test_the_single_task_endpoint_reports_who_started_it(
    async_client, task_endpoint_overrides
) -> None:
    response = await async_client.get(f"/v1/workspaces/acme/tasks/{task_endpoint_overrides.id}")

    assert response.status_code == 200, response.text
    assert response.json()["created_by"] == CREATOR_ID


@pytest.mark.asyncio
async def test_reading_tasks_never_calls_the_identity_provider(
    async_client, task_endpoint_overrides, monkeypatch
) -> None:
    """The regression this refactor exists to prevent.

    Attaching a resolved name to the task read model made listing tasks depend
    on Kratos being up and quick. Nothing on this path may reach for it again.
    """
    from agentarea_common.auth import identity_directory

    called = False

    def _fail_if_used():
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(identity_directory, "get_identity_directory", _fail_if_used)

    assert (await async_client.get("/v1/workspaces/acme/tasks/")).status_code == 200
    assert (
        await async_client.get(f"/v1/workspaces/acme/tasks/{task_endpoint_overrides.id}")
    ).status_code == 200
    assert not called
