"""A task's read endpoints must survive the deletion of the agent that ran it.

Reproduces a real case: task 03dd3f6f… on the RU deployment completed fine, its
agent d7b1f22e… was later deleted, and the Events tab went blank. The read
endpoints opened with `agent_service.get(agent_id)` and 404'd before reading
anything — so one deleted agent took the history, the live stream and the
status of every task it had ever run down with it. `agent_id` is a route
parameter; the task lookup already proves both workspace membership and
task↔agent ownership, so the agent-existence gate only ever hid data.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import (
    get_read_agent_service,
    get_read_task_service,
    get_temporal_workflow_service,
)
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base.dependencies import get_read_repository_factory
from agentarea_tasks.domain.models import AgentTask
from httpx import ASGITransport, AsyncClient

DELETED_AGENT_ID = uuid4()
TASK_ID = uuid4()


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def surviving_task() -> AgentTask:
    return AgentTask(
        id=TASK_ID,
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=DELETED_AGENT_ID,
        status="completed",
        execution_id="exec-1",
    )


def _event_record():
    record = MagicMock()
    record.id = uuid4()
    record.task_id = TASK_ID
    record.timestamp = datetime.now(UTC)
    record.event_type = "task.completed"
    record.data = {"message": "done", "execution_id": "exec-1"}
    record.metadata = {}
    return record


@pytest.fixture
def task_service(surviving_task):
    service = AsyncMock()
    service.get_task.return_value = surviving_task
    service.get_task_with_workflow_status.return_value = surviving_task
    return service


@pytest.fixture(autouse=True)
def override_dependencies(task_service, monkeypatch):
    """The agent is gone; the task and its events are still in the workspace."""
    agent_service = AsyncMock()
    agent_service.get.return_value = None

    event_repository = AsyncMock()
    event_repository.list_for_task.return_value = ([_event_record()], 1)
    repository_factory = MagicMock()
    repository_factory.create_repository.return_value = event_repository

    workflow_service = AsyncMock()
    workflow_service.get_workflow_status.return_value = {"status": "completed"}

    user_context = MagicMock()
    user_context.user_id = "test_user"
    user_context.workspace_id = "test_workspace"

    # The status endpoint fans out to the sandbox manager for artifacts; that is
    # not what these tests are about.
    monkeypatch.setattr(
        "agentarea_api.api.v1.agents_tasks._list_task_artifact_items",
        AsyncMock(return_value=[]),
    )

    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_read_agent_service] = lambda: agent_service
    app.dependency_overrides[get_read_repository_factory] = lambda: repository_factory
    app.dependency_overrides[get_temporal_workflow_service] = lambda: workflow_service
    app.dependency_overrides[get_user_context] = lambda: user_context
    yield
    for dep in (
        get_read_task_service,
        get_read_agent_service,
        get_read_repository_factory,
        get_temporal_workflow_service,
        get_user_context,
    ):
        app.dependency_overrides.pop(dep, None)


@pytest.mark.asyncio
async def test_event_history_is_readable_after_the_agent_is_deleted(async_client):
    response = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}/events")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["events"][0]["event_type"] == "task.completed"


@pytest.mark.asyncio
async def test_event_stream_opens_after_the_agent_is_deleted(async_client):
    response = await async_client.get(
        f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}/events/stream"
    )

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_task_detail_and_status_are_readable_after_the_agent_is_deleted(async_client):
    """The task page reads both of these; neither may be gated on the agent."""
    detail = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "completed"

    status = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}/status")
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_a_task_belonging_to_another_agent_is_still_a_404(async_client, task_service):
    """Dropping the agent gate must not drop the task<->agent ownership check."""
    task_service.get_task_with_workflow_status.return_value = AgentTask(
        id=TASK_ID,
        title="task",
        description="someone else's task",
        query="q",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=uuid4(),
        status="completed",
    )

    response = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@pytest.mark.asyncio
@pytest.mark.parametrize("suffix", ["/events", "/events/stream"])
async def test_events_reject_an_agent_id_that_does_not_own_the_task(
    async_client, task_service, suffix
):
    """`agent_id` is echoed into every event, so it has to own the task.

    Without this the caller picks the `agent_id` stamped onto another agent's
    event history — the same fabricated-identifier defect this series removes.
    """
    task_service.get_task.return_value = AgentTask(
        id=TASK_ID,
        title="task",
        description="someone else's task",
        query="q",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=uuid4(),
        status="completed",
        execution_id="exec-9",
    )

    response = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}{suffix}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"


@pytest.mark.asyncio
async def test_a_task_that_does_not_exist_is_still_a_404(async_client, task_service):
    task_service.get_task.return_value = None

    response = await async_client.get(f"/v1/agents/{DELETED_AGENT_ID}/tasks/{TASK_ID}/events")

    assert response.status_code == 404
    assert response.json()["detail"] == "Task not found"
