"""Scheduled (one-shot, future) task dispatch."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_tasks.direct_task_manager import DirectTaskManager
from agentarea_tasks.domain.base_service import BaseTaskService
from agentarea_tasks.domain.exceptions import SchedulingNotSupportedError
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from pydantic import ValidationError


def _task(**overrides) -> AgentTask:
    fields = {
        "id": uuid4(),
        "title": "nightly digest",
        "description": "build the digest",
        "query": "build the digest",
        "user_id": "user-1",
        "workspace_id": "workspace-1",
        "agent_id": uuid4(),
        "status": "pending",
        "created_at": datetime.now(UTC),
        "task_parameters": {},
        "metadata": {},
    }
    fields.update(overrides)
    return AgentTask(**fields)


def _manager(task: AgentTask) -> TemporalTaskManager:
    manager = TemporalTaskManager.__new__(TemporalTaskManager)
    domain_task = manager._agent_task_to_task(task)
    repository = MagicMock()
    repository.update_status = AsyncMock(return_value=domain_task)
    repository.update_task = AsyncMock(return_value=domain_task)
    executor = MagicMock()
    executor.start_workflow = AsyncMock(return_value=f"task-{task.id}")
    manager.task_repository = repository
    manager.temporal_executor = executor
    manager.task_queue = "agent-tasks"
    return manager


def test_scheduled_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValidationError):
        _task(scheduled_at=datetime(2030, 1, 1, 12, 0))


@pytest.mark.asyncio
async def test_scheduled_task_starts_workflow_with_a_delay() -> None:
    task = _task(scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    manager = _manager(task)

    await manager.submit_task(task)

    config = manager.temporal_executor.start_workflow.await_args.kwargs["config"]
    assert timedelta(minutes=59) < config.start_delay <= timedelta(hours=1)


@pytest.mark.asyncio
async def test_scheduled_task_is_not_marked_running() -> None:
    task = _task(scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    manager = _manager(task)

    await manager.submit_task(task)

    assert manager.task_repository.update_status.await_args.args[1] == "scheduled"


@pytest.mark.asyncio
async def test_unscheduled_task_carries_no_delay_and_runs() -> None:
    task = _task()
    manager = _manager(task)

    await manager.submit_task(task)

    config = manager.temporal_executor.start_workflow.await_args.kwargs["config"]
    assert config.start_delay is None
    assert manager.task_repository.update_status.await_args.args[1] == "running"


@pytest.mark.asyncio
async def test_due_time_already_passed_dispatches_without_a_negative_delay() -> None:
    task = _task(scheduled_at=datetime.now(UTC) - timedelta(minutes=5))
    manager = _manager(task)

    await manager.submit_task(task)

    config = manager.temporal_executor.start_workflow.await_args.kwargs["config"]
    assert config.start_delay is None


def test_agent_task_to_task_preserves_scheduled_at() -> None:
    run_at = datetime.now(UTC) + timedelta(days=2)
    manager = TemporalTaskManager.__new__(TemporalTaskManager)

    domain_task = manager._agent_task_to_task(_task(scheduled_at=run_at))
    assert domain_task.scheduled_at == run_at

    assert manager._task_to_agent_task(domain_task).scheduled_at == run_at


@pytest.mark.asyncio
async def test_direct_manager_refuses_to_run_a_scheduled_task_now() -> None:
    """The in-process manager has no timer; running it immediately would be wrong."""
    task = _task(scheduled_at=datetime.now(UTC) + timedelta(hours=1))
    manager = DirectTaskManager.__new__(DirectTaskManager)
    manager.task_repository = MagicMock()
    manager._tasks = {}

    with pytest.raises(SchedulingNotSupportedError):
        await manager.submit_task(task)


class _EchoTaskRepository:
    """Stands in for the workspace-scoped repository, which stamps owner and tenant."""

    def __init__(self) -> None:
        self.rows: dict = {}

    async def create_task(self, task):
        row = task.model_copy(update={"user_id": "user-1", "workspace_id": "workspace-1"})
        self.rows[row.id] = row
        return row

    async def get_task(self, task_id):
        return self.rows.get(task_id)


class _TaskService(BaseTaskService):
    async def submit_task(self, task: AgentTask) -> AgentTask:
        raise NotImplementedError


@pytest.mark.asyncio
async def test_create_task_persists_scheduled_at_and_returns_it() -> None:
    run_at = datetime.now(UTC) + timedelta(hours=3)
    repository = _EchoTaskRepository()
    service = _TaskService(repository, event_broker=MagicMock())

    created = await service.create_task(_task(scheduled_at=run_at))

    assert repository.rows[created.id].scheduled_at == run_at
    assert created.scheduled_at == run_at


@pytest.mark.asyncio
async def test_get_task_carries_scheduled_at() -> None:
    run_at = datetime.now(UTC) + timedelta(hours=3)
    repository = _EchoTaskRepository()
    service = _TaskService(repository, event_broker=MagicMock())
    created = await service.create_task(_task(scheduled_at=run_at))

    fetched = await service.get_task(created.id)

    assert fetched is not None
    assert fetched.scheduled_at == run_at
