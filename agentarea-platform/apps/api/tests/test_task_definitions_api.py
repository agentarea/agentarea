"""Saved tasks over HTTP: a run of one is the caller's run, refused without execute on its agent."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_api.api.deps.services import get_task_definition_service
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container
from agentarea_tasks.application.task_definition_service import TaskDefinitionService
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.domain.task_definitions import TaskDefinition
from agentarea_tasks.infrastructure.task_definition_repository import TaskDefinitionRepository
from httpx import ASGITransport, AsyncClient

CALLER = UserContext(user_id="user-1", workspace_id="ws-1")
AGENT = uuid4()
OTHER_AGENT = uuid4()
BASE = "/v1/workspaces/acme/task-definitions"


class _Definitions:
    def __init__(self) -> None:
        self.rows: dict[UUID, TaskDefinition] = {}

    async def get(self, _id):
        return None

    async def get_definition(self, definition_id: UUID) -> TaskDefinition | None:
        return self.rows.get(definition_id)

    async def create_definition(self, *, name, description, agent_id, parameters):
        now = datetime.now(UTC)
        definition = TaskDefinition(
            id=uuid4(),
            name=name,
            description=description,
            agent_id=agent_id,
            parameters=parameters,
            workspace_id=CALLER.workspace_id,
            created_by=CALLER.user_id,
            created_at=now,
            updated_at=now,
        )
        self.rows[definition.id] = definition
        return definition


class _Agents:
    async def get(self, agent_id):
        return SimpleNamespace(id=agent_id) if agent_id in (AGENT, OTHER_AGENT) else None


class _Session:
    """Answers how many triggers run a saved task."""

    def __init__(self) -> None:
        self.triggers_running = 0

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one=lambda: self.triggers_running)


class _Permissions(PermissionService):
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed

    async def check(self, subject, permission, resource_type, resource_id) -> bool:
        return self.allowed or permission != "execute"


def _started(payload, **kwargs) -> AgentTask:
    return AgentTask(
        title=payload.description,
        description=payload.description,
        query=payload.description,
        user_id=kwargs["user_id"],
        workspace_id=kwargs["workspace_id"],
        agent_id=payload.agent_id,
        task_parameters=payload.parameters,
        provenance=kwargs["provenance"],
        status="running",
        execution_id="agent-task-1",
    )


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def wired():
    container = get_container()
    saved = dict(container._singletons)
    repositories = {TaskDefinitionRepository: _Definitions(), AgentRepository: _Agents()}
    session = _Session()
    factory = SimpleNamespace(
        session=session, user_context=CALLER, create_repository=lambda cls: repositories[cls]
    )
    task_service = AsyncMock()
    task_service.start_run.side_effect = _started
    service = TaskDefinitionService(factory, task_service)  # type: ignore[arg-type]
    app.dependency_overrides[get_user_context] = lambda: CALLER
    app.dependency_overrides[get_task_definition_service] = lambda: service

    def allow_execute(allowed: bool) -> AsyncMock:
        container.register_singleton(PermissionService, _Permissions(allowed))
        return task_service

    allow_execute.session = session  # type: ignore[attr-defined]
    yield allow_execute
    app.dependency_overrides.pop(get_user_context, None)
    app.dependency_overrides.pop(get_task_definition_service, None)
    container._singletons.clear()
    container._singletons.update(saved)


async def _save(client) -> dict:
    response = await client.post(
        f"{BASE}/",
        json={
            "name": "Morning digest",
            "description": "Summarise yesterday's tickets",
            "agent_id": str(AGENT),
            "parameters": {"region": "eu"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_run_records_the_saved_task_and_who_started_it(client, wired):
    task_service = wired(True)
    saved = await _save(client)

    response = await client.post(f"{BASE}/{saved['id']}/run", json={"parameters": {"day": "mon"}})

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["agent_id"] == str(AGENT)
    assert body["description"] == "Summarise yesterday's tickets"
    assert body["parameters"] == {"region": "eu", "day": "mon"}
    assert body["provenance"]["task_definition_id"] == saved["id"]
    assert body["provenance"]["origin_type"] == "user"
    assert body["provenance"]["origin_id"] == CALLER.user_id
    assert body["provenance"]["source_identity"] == f"user:{CALLER.user_id}"
    task_service.start_run.assert_awaited_once()


async def test_a_caller_without_execute_on_the_agent_is_refused(client, wired):
    task_service = wired(False)
    saved = await _save(client)

    response = await client.post(f"{BASE}/{saved['id']}/run")

    assert response.status_code == 403
    task_service.start_run.assert_not_awaited()


async def test_a_saved_task_for_an_agent_outside_the_workspace_is_refused(client, wired):
    wired(True)

    response = await client.post(
        f"{BASE}/",
        json={"name": "x", "description": "do it", "agent_id": str(uuid4())},
    )

    assert response.status_code == 400


async def test_an_unknown_saved_task_is_not_found(client, wired):
    task_service = wired(True)

    assert (await client.get(f"{BASE}/{uuid4()}")).status_code == 404
    assert (await client.post(f"{BASE}/{uuid4()}/run")).status_code == 404
    task_service.start_run.assert_not_awaited()


async def test_a_saved_task_a_trigger_runs_cannot_change_agent_or_be_deleted(client, wired):
    wired(True)
    saved = await _save(client)
    wired.session.triggers_running = 1

    moved = await client.put(f"{BASE}/{saved['id']}", json={"agent_id": str(OTHER_AGENT)})
    deleted = await client.delete(f"{BASE}/{saved['id']}")

    assert (moved.status_code, deleted.status_code) == (409, 409)
    assert (await client.get(f"{BASE}/{saved['id']}")).json()["agent_id"] == str(AGENT)
