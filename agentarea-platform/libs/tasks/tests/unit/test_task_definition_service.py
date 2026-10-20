"""A saved task names an agent of its workspace, and a run of it is the caller's run of that agent."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container
from agentarea_tasks.application.task_definition_service import TaskDefinitionService
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.domain.task_definitions import (
    TaskDefinition,
    TaskDefinitionInUseError,
    TaskDefinitionNotFoundError,
    TaskDefinitionValidationError,
)
from agentarea_tasks.infrastructure.task_definition_repository import TaskDefinitionRepository
from agentarea_tasks.schemas.dto import TaskDefinitionCreate, TaskDefinitionUpdate
from agentarea_triggers.infrastructure.repository import TriggerRepository
from fastapi import HTTPException
from pydantic import ValidationError

CALLER = UserContext(user_id="user-1", workspace_id="ws-1")
AGENT = uuid4()
OTHER_AGENT = uuid4()


class _Definitions:
    def __init__(self) -> None:
        self.rows: dict[UUID, TaskDefinition] = {}

    async def get(self, _id):
        return None

    async def get_definition(self, definition_id: UUID) -> TaskDefinition | None:
        return self.rows.get(definition_id)

    async def list_definitions(self, *, agent_id=None, limit=100, offset=0):
        return [d for d in self.rows.values() if agent_id in (None, d.agent_id)][:limit]

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

    async def update_definition(self, definition_id: UUID, **changes):
        self.rows[definition_id] = self.rows[definition_id].model_copy(update=changes)
        return self.rows[definition_id]

    async def delete(self, definition_id: UUID) -> bool:
        return self.rows.pop(definition_id, None) is not None


class _Agents:
    async def get(self, agent_id):
        return SimpleNamespace(id=agent_id) if agent_id in (AGENT, OTHER_AGENT) else None


class _Permissions(PermissionService):
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.asked: list[tuple[str, str, str]] = []

    async def check(self, subject, permission, resource_type, resource_id) -> bool:
        self.asked.append((permission, resource_type, resource_id))
        return self.allowed


@pytest.fixture
def permissions():
    container = get_container()
    saved = dict(container._singletons)

    def install(allowed: bool) -> _Permissions:
        pdp = _Permissions(allowed)
        container.register_singleton(PermissionService, pdp)
        return pdp

    yield install
    container._singletons.clear()
    container._singletons.update(saved)


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
    )


class _Session:
    """Takes the audit events the service writes."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        pass


class _Triggers:
    """Answers the one count the service asks: how many triggers run a definition."""

    def __init__(self, triggers_running: int) -> None:
        self.triggers_running = triggers_running

    async def count(self, *, task_definition_id: UUID) -> int:
        return self.triggers_running


def _service(triggers_running: int = 0) -> tuple[TaskDefinitionService, _Definitions, AsyncMock]:
    definitions = _Definitions()
    repositories = {
        TaskDefinitionRepository: definitions,
        AgentRepository: _Agents(),
        TriggerRepository: _Triggers(triggers_running),
    }
    factory = SimpleNamespace(
        session=_Session(),
        user_context=CALLER,
        create_repository=lambda cls: repositories[cls],
    )
    task_service = AsyncMock()
    task_service.start_run.side_effect = _started
    return TaskDefinitionService(factory, task_service), definitions, task_service  # type: ignore[arg-type]


def _create(**overrides) -> TaskDefinitionCreate:
    return TaskDefinitionCreate(
        **{
            "name": "Morning digest",
            "description": "Summarise yesterday's tickets",
            "agent_id": AGENT,
            "parameters": {"model_override": "fast"},
            **overrides,
        }
    )


async def test_a_saved_task_names_an_agent_of_the_workspace():
    service, definitions, _ = _service()

    with pytest.raises(TaskDefinitionValidationError, match="does not exist"):
        await service.create(_create(agent_id=uuid4()))

    assert definitions.rows == {}


@pytest.mark.parametrize(
    "overrides",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 256},
        {"description": ""},
        {"description": "  \n"},
        {"parameters": {"delivery_address": {"channel": "x"}}},
    ],
)
def test_a_saved_task_needs_a_name_a_text_and_no_reserved_parameters(overrides):
    with pytest.raises(ValidationError):
        _create(**overrides)


async def test_moving_a_saved_task_to_another_agent_checks_that_agent():
    service, _, _ = _service()
    definition = await service.create(_create())

    with pytest.raises(TaskDefinitionValidationError):
        await service.update(definition.id, TaskDefinitionUpdate(agent_id=uuid4()))

    moved = await service.update(definition.id, TaskDefinitionUpdate(agent_id=OTHER_AGENT))
    assert moved.agent_id == OTHER_AGENT
    assert moved.name == definition.name


async def test_a_saved_task_a_trigger_runs_keeps_its_agent_and_cannot_be_deleted():
    service, definitions, _ = _service(triggers_running=2)
    definition = await service.create(_create())

    with pytest.raises(TaskDefinitionInUseError, match="2 trigger"):
        await service.update(definition.id, TaskDefinitionUpdate(agent_id=OTHER_AGENT))
    with pytest.raises(TaskDefinitionInUseError):
        await service.delete(definition.id)

    assert definitions.rows[definition.id].agent_id == AGENT


async def test_a_saved_task_a_trigger_runs_may_still_be_reworded():
    service, _, _ = _service(triggers_running=1)
    definition = await service.create(_create())

    renamed = await service.update(definition.id, TaskDefinitionUpdate(name="Evening digest"))

    assert renamed.name == "Evening digest"


async def test_resending_the_same_agent_is_not_moving_the_saved_task():
    """The edit form sends every field; keeping the agent is not changing it."""
    service, _, _ = _service(triggers_running=1)
    definition = await service.create(_create())

    updated = await service.update(
        definition.id, TaskDefinitionUpdate(agent_id=AGENT, name="Evening digest")
    )

    assert (updated.agent_id, updated.name) == (AGENT, "Evening digest")


async def test_an_unknown_saved_task_is_not_found():
    service, _, _ = _service()

    with pytest.raises(TaskDefinitionNotFoundError):
        await service.get(uuid4())
    with pytest.raises(TaskDefinitionNotFoundError):
        await service.run(uuid4())


async def test_a_run_is_the_callers_run_of_the_saved_agent_and_text(permissions):
    pdp = permissions(True)
    service, _, task_service = _service()
    definition = await service.create(_create())

    task = await service.run(definition.id, parameters={"region": "eu"})

    assert pdp.asked == [("execute", "agent", str(AGENT))]
    payload = task_service.start_run.await_args.args[0]
    assert payload.agent_id == AGENT
    assert payload.description == "Summarise yesterday's tickets"
    assert payload.parameters == {"model_override": "fast", "region": "eu"}
    assert task.provenance.origin_type == "user"
    assert task.provenance.origin_id == CALLER.user_id
    assert task.provenance.source_identity == f"user:{CALLER.user_id}"
    assert task.provenance.task_definition_id == definition.id


async def test_a_caller_who_may_not_run_the_agent_starts_nothing(permissions):
    permissions(False)
    service, _, task_service = _service()
    definition = await service.create(_create())

    with pytest.raises(HTTPException) as refused:
        await service.run(definition.id)

    assert refused.value.status_code == 403
    task_service.start_run.assert_not_awaited()
