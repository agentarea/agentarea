"""A task's read model says what started it: the trigger, the event, the parent task.

The tasks table has carried origin, correlation, causation and parent ids since
event streams landed, but every read dropped them, so a trigger-fired task read
as one a person started.
"""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_agent_service, get_read_task_service
from agentarea_api.api.v1.agents_tasks import TaskResponse, TaskWithAgent
from agentarea_api.main import app
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RunsToolset
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_tasks.domain.base_service import BaseTaskService
from agentarea_tasks.domain.models import AgentTask, Task, TaskProvenance
from httpx import ASGITransport, AsyncClient

TRIGGER_ID = str(uuid4())
EVENT_ID = str(uuid4())
ROOT_EVENT_ID = str(uuid4())
PARENT_ID = uuid4()
PROVENANCE = TaskProvenance(
    origin_type="trigger",
    origin_id=TRIGGER_ID,
    correlation_id=ROOT_EVENT_ID,
    causation_id=EVENT_ID,
    parent_task_id=PARENT_ID,
)
EXPECTED = {
    "origin_type": "trigger",
    "origin_id": TRIGGER_ID,
    "correlation_id": ROOT_EVENT_ID,
    "causation_id": EVENT_ID,
    "parent_task_id": str(PARENT_ID),
}


def _task() -> Task:
    now = datetime.now(UTC)
    return Task(
        id=uuid4(),
        agent_id=uuid4(),
        description="Reply naming the order id",
        parameters={},
        status="completed",
        created_at=now,
        updated_at=now,
        user_id="u",
        workspace_id="workspace-1",
        provenance=PROVENANCE,
    )


def test_the_agent_task_conversion_keeps_provenance() -> None:
    converted = BaseTaskService._task_to_agent_task(MagicMock(), _task())
    assert converted.provenance == PROVENANCE


def test_the_task_responses_carry_provenance() -> None:
    task = AgentTask(
        title="t",
        description="d",
        query="d",
        user_id="u",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        provenance=PROVENANCE,
    )
    response = TaskResponse.from_agent_task(task)
    assert response.model_dump(mode="json")["provenance"] == EXPECTED
    with_agent = TaskWithAgent.from_task_response(response, "SEO")
    assert with_agent.model_dump(mode="json")["provenance"] == EXPECTED


def test_a_task_nothing_recorded_for_reads_as_unknown_origin() -> None:
    response = TaskWithAgent.from_task_response(
        TaskResponse.from_agent_task(
            AgentTask(
                title="t",
                description="d",
                query="d",
                user_id="u",
                workspace_id="workspace-1",
                agent_id=uuid4(),
            )
        ),
        None,
    )
    assert response.model_dump(mode="json")["provenance"] == dict.fromkeys(EXPECTED)


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def task_endpoints():
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
    user_context.user_id = "u"
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
async def test_the_task_list_and_detail_endpoints_report_provenance(
    async_client, task_endpoints
) -> None:
    listed = await async_client.get("/v1/workspaces/acme/tasks/")
    single = await async_client.get(f"/v1/workspaces/acme/tasks/{task_endpoints.id}")

    assert listed.status_code == 200, listed.text
    assert single.status_code == 200, single.text
    assert listed.json()[0]["provenance"] == EXPECTED
    assert single.json()["provenance"] == EXPECTED


@pytest.mark.asyncio
async def test_the_runs_toolset_reports_provenance(monkeypatch) -> None:
    task = SimpleNamespace(
        id=uuid4(),
        title="t",
        status="completed",
        agent_id=uuid4(),
        query="q",
        provenance=PROVENANCE,
    )

    @asynccontextmanager
    async def fake_context():
        yield None, UserContext(user_id="u", workspace_id="w"), SimpleNamespace(), None, None

    async def fake_build(_repo_factory, _broker):
        return SimpleNamespace(get_task=AsyncMock(return_value=task))

    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(runs_toolset, "_build_task_service", fake_build)

    got = json.loads(await RunsToolset().get(run_id=str(task.id)))

    assert got["provenance"] == EXPECTED
