"""A follow-up routed into a running workflow goes out once per delivery, however often it is retried."""

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

from agentarea_tasks.domain.models import AgentTask, Task
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService


class _Running:
    def __init__(self, task: Task):
        self.task = task

    async def find_active_by_agent_and_chat(self, agent_id: UUID, chat_id: str, limit: int = 5):
        return [self.task]


class _Executor:
    def __init__(self, answers: list[bool]):
        self.answers = answers
        self.signals: list[tuple[str, str, dict[str, Any]]] = []

    async def send_workflow_command(self, execution_id: str, command: str, payload: dict):
        self.signals.append((execution_id, command, payload))
        return self.answers.pop(0)


class _Claims:
    """One delivery's durable claim, shared by every attempt at that delivery."""

    def __init__(self):
        self.claimed: UUID | None = None
        self.released = 0

    async def claim(self, task_id: UUID) -> bool:
        if self.claimed is not None:
            return False
        self.claimed = task_id
        return True

    async def release(self) -> None:
        self.claimed = None
        self.released += 1


def _running_task() -> Task:
    now = datetime.now(UTC)
    task_id = uuid4()
    return Task(
        id=task_id,
        agent_id=uuid4(),
        description="Chat",
        parameters={"channel_origin": {"chat_id": "c-1"}},
        status="running",
        execution_id=f"task-{task_id}",
        user_id="user-1",
        workspace_id="ws-1",
        created_at=now,
        updated_at=now,
    )


def _service(running: Task, executor: _Executor) -> TaskService:
    factory = MagicMock()
    factory.create_repository = MagicMock(
        side_effect=lambda cls: _Running(running) if cls is TaskRepository else MagicMock()
    )
    engine = MagicMock()
    engine.temporal_executor = executor
    return TaskService(
        repository_factory=factory,
        event_broker=AsyncMock(),
        task_manager=engine,
        policy_resolver=AsyncMock(),
    )


def _delivery(running: Task, delivery_id: UUID) -> AgentTask:
    return AgentTask(
        id=delivery_id,
        title="Trigger: chat",
        description="hello again",
        query="hello again",
        user_id="user-1",
        workspace_id="ws-1",
        agent_id=running.agent_id,
        task_parameters={"channel_origin": {"chat_id": "c-1"}},
    )


async def test_a_redelivered_follow_up_is_queued_once():
    running = _running_task()
    executor = _Executor([True, True])
    service = _service(running, executor)
    claims, delivery_id = _Claims(), uuid4()

    first = await service.route_or_submit_task(
        _delivery(running, delivery_id), follow_up_claim=claims
    )
    again = await service.route_or_submit_task(
        _delivery(running, delivery_id), follow_up_claim=claims
    )

    assert len(executor.signals) == 1
    assert (first.status, first.id) == ("routed", running.id)
    assert (again.status, again.id) == ("routed", running.id)
    assert claims.claimed == running.id


async def test_a_signal_that_did_not_go_out_withdraws_its_claim():
    running = _running_task()
    executor = _Executor([False, True])
    service = _service(running, executor)
    claims, delivery_id = _Claims(), uuid4()
    service.create_task_with_policy = AsyncMock(side_effect=RuntimeError("no new task here"))

    try:
        await service.route_or_submit_task(_delivery(running, delivery_id), follow_up_claim=claims)
    except RuntimeError:
        pass
    assert claims.released == 1 and claims.claimed is None

    routed = await service.route_or_submit_task(
        _delivery(running, delivery_id), follow_up_claim=claims
    )
    assert routed.status == "routed"
    assert len(executor.signals) == 2


async def test_a_message_whose_event_needs_a_file_starts_its_own_run():
    running = _running_task()
    executor = _Executor([True])
    service = _service(running, executor)
    delivery = _delivery(running, uuid4())
    delivery.task_parameters = {
        **delivery.task_parameters,
        "trigger_data": {"text": "hello again"},
        "trigger_event_file": "trigger-event-3.json",
    }

    assert await service._try_route_to_active_workflow(delivery, "c-1") is None
    assert executor.signals == []
