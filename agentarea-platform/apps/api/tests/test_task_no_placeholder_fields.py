"""A task record must never invent values for fields it could not resolve.

`agent_name="Unknown"` and `execution_id="unknown"` used to be substituted when
the lookup came up empty. Both are indistinguishable from real values, so the
UI rendered a confident "Unknown" breadcrumb over what was actually a missing
agent — and callers had no way to detect the difference. Absent means null.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.agents_tasks import TaskEvent, TaskResponse, TaskWithAgent
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_tasks.domain.models import AgentTask, Task
from httpx import ASGITransport, AsyncClient


def _agent_task() -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="completed",
    )


def test_agent_name_is_null_when_the_agent_does_not_resolve() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    with_agent = TaskWithAgent.from_task_response(response, None)

    assert with_agent.agent_name is None
    assert with_agent.model_dump()["agent_name"] is None


def test_agent_name_is_carried_through_when_it_does_resolve() -> None:
    response = TaskResponse.from_agent_task(_agent_task())

    with_agent = TaskWithAgent.from_task_response(response, "neuresearch")

    assert with_agent.agent_name == "neuresearch"


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_the_task_endpoint_returns_a_null_agent_name_for_a_deleted_agent(async_client):
    """The contract that matters is the endpoint's, not the helper's.

    GET /v1/tasks/{id} is what the task page reads; it builds TaskWithAgent
    inline rather than through from_task_response.
    """
    # get_task_by_id reads through task_repository._orm_to_domain, which yields
    # a Task (not an AgentTask) — the model the endpoint's fields come from.
    task = Task(
        id=uuid4(),
        agent_id=uuid4(),
        description="do the thing",
        parameters={},
        status="completed",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    task_service = AsyncMock()
    task_service.task_repository.get_by_id = AsyncMock(return_value=object())
    task_service.task_repository._orm_to_domain = MagicMock(return_value=task)

    agent_service = AsyncMock()
    agent_service.get_with_catalog.return_value = None

    user_context = MagicMock()
    user_context.user_id = "user-1"
    user_context.workspace_id = "workspace-1"

    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_read_agent_service] = lambda: agent_service
    app.dependency_overrides[get_user_context] = lambda: user_context
    try:
        response = await async_client.get(f"/v1/tasks/{task.id}")
    finally:
        for dep in (get_read_task_service, get_read_agent_service, get_user_context):
            app.dependency_overrides.pop(dep, None)

    assert response.status_code == 200, response.text
    assert response.json()["agent_name"] is None


def test_task_event_execution_id_is_null_rather_than_a_placeholder() -> None:
    event = TaskEvent(
        id=str(uuid4()),
        task_id=str(uuid4()),
        agent_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        event_type="task.started",
        message="started",
    )

    assert event.execution_id is None
