"""Unit tests for the task submission paths in TaskService.

These tests pin the contract between `submit_task`, `create_and_execute_task_with_workflow`,
and `task_manager.submit_task` so that A2A, MCP, and REST stay aligned. Drift here was the
root cause of A2A losing channel routing and metadata defaults.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_governance.domain.policies import EffectivePolicy
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.task_service import TaskService


def _make_service(temporal_executor=None):
    """Build a TaskService with mocked deps. Returns (service, mocks)."""
    task_repo = MagicMock()
    task_repo.create_task = AsyncMock(side_effect=lambda t: t)
    task_repo.find_active_by_agent_and_chat = AsyncMock(return_value=[])

    agent_stub = MagicMock(id=uuid4())
    agent_stub.name = "stub-agent"  # MagicMock(name=...) is the mock's own name, not a field
    agent_repo = MagicMock()
    agent_repo.get = AsyncMock(return_value=agent_stub)

    repo_factory = MagicMock()

    def create_repository(cls):
        if cls is TaskRepository:
            return task_repo
        if cls is AgentRepository:
            return agent_repo
        raise AssertionError(f"unexpected repository request: {cls}")

    repo_factory.create_repository = create_repository

    event_broker = AsyncMock()

    task_manager = MagicMock()

    async def _submit(t):
        t.status = "running"
        t.execution_id = f"task-{t.id}"
        return t

    task_manager.submit_task = AsyncMock(side_effect=_submit)
    task_manager.temporal_executor = temporal_executor

    policy_resolver = MagicMock()
    policy_resolver.resolve = AsyncMock(return_value=EffectivePolicy())
    policy_resolver.snapshot = AsyncMock()

    service = TaskService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        policy_resolver=policy_resolver,
    )
    # Short-circuit create_task for unit isolation (bypasses audit decorator + db plumbing).
    service.create_task = AsyncMock(side_effect=lambda t: t)

    return service, {
        "task_repo": task_repo,
        "agent_repo": agent_repo,
        "task_manager": task_manager,
        "event_broker": event_broker,
    }


def _build_task(**overrides):
    base = dict(
        id=uuid4(),
        title="A2A Message Task",
        description="Hello from A2A",
        query="Hello from A2A",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        status="submitted",
        task_parameters={},
        metadata={
            "task_source": "a2a_protocol",
            "a2a_method": "message/send",
        },
    )
    base.update(overrides)
    return AgentTask(**base)


@pytest.mark.asyncio
async def test_submit_task_routes_through_canonical_method_and_invokes_task_manager():
    """submit_task() must end at task_manager.submit_task and produce a stored task."""
    service, mocks = _make_service()
    task = _build_task()

    result = await service.submit_task(task)

    mocks["agent_repo"].get.assert_awaited_once_with(task.agent_id)
    mocks["task_manager"].submit_task.assert_awaited_once()
    submitted_arg = mocks["task_manager"].submit_task.await_args.args[0]
    assert isinstance(submitted_arg, AgentTask)
    assert result.execution_id is not None


@pytest.mark.asyncio
async def test_submit_task_preserves_caller_provided_id_metadata_and_parameters():
    """A2A pre-builds the AgentTask. The id, metadata and task_parameters must survive."""
    service, mocks = _make_service()
    pre_id = uuid4()
    task = _build_task(
        id=pre_id,
        task_parameters={"channel_origin": {"chat_id": "c-99"}, "tone": "warm"},
        metadata={"task_source": "a2a_protocol", "request_id": "req-7"},
    )

    await service.submit_task(task)

    submitted_arg = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted_arg.id == pre_id
    assert submitted_arg.task_parameters == {
        "channel_origin": {"chat_id": "c-99"},
        "tone": "warm",
    }
    # Caller metadata preserved AND merged with canonical defaults
    assert submitted_arg.metadata["task_source"] == "a2a_protocol"
    assert submitted_arg.metadata["request_id"] == "req-7"


@pytest.mark.asyncio
async def test_create_and_execute_sets_default_metadata():
    """REST callers rely on metadata.created_via, agent_name, requires_human_approval defaults."""
    service, mocks = _make_service()
    agent_id = uuid4()

    await service.create_and_execute_task_with_workflow(
        agent_id=agent_id,
        description="generate vk post",
        workspace_id="ws-abc",
        user_id="user-123",
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.metadata["created_via"] == "api"
    assert submitted.metadata["requires_human_approval"] is False
    assert submitted.metadata["agent_name"] == "stub-agent"


@pytest.mark.asyncio
async def test_submit_task_routes_to_active_workflow_when_chat_id_present():
    """submit_task with channel_origin.chat_id must attempt routing before creating a new task."""
    executor = MagicMock()
    executor.send_workflow_command = AsyncMock(return_value=True)
    service, mocks = _make_service(temporal_executor=executor)

    candidate = MagicMock(
        id=uuid4(),
        execution_id="task-existing",
        description="prev",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        parameters={},
    )
    mocks["task_repo"].find_active_by_agent_and_chat = AsyncMock(return_value=[candidate])

    task = _build_task(task_parameters={"channel_origin": {"chat_id": "c-99"}})

    result = await service.submit_task(task)

    # Routed task short-circuits — no new submit_task on task_manager
    mocks["task_manager"].submit_task.assert_not_awaited()
    executor.send_workflow_command.assert_awaited_once()
    assert result.status == "routed"
    assert result.execution_id == "task-existing"


@pytest.mark.asyncio
async def test_create_and_execute_routes_to_active_workflow_when_chat_id_present():
    """REST path also routes to active workflow when channel_origin.chat_id is set."""
    executor = MagicMock()
    executor.send_workflow_command = AsyncMock(return_value=True)
    service, mocks = _make_service(temporal_executor=executor)

    candidate = MagicMock(
        id=uuid4(),
        execution_id="task-existing",
        description="prev",
        user_id="user-123",
        workspace_id="ws-abc",
        agent_id=uuid4(),
        parameters={},
    )
    mocks["task_repo"].find_active_by_agent_and_chat = AsyncMock(return_value=[candidate])

    result = await service.create_and_execute_task_with_workflow(
        agent_id=uuid4(),
        description="follow-up",
        workspace_id="ws-abc",
        parameters={"channel_origin": {"chat_id": "c-99"}},
        user_id="user-123",
    )

    mocks["task_manager"].submit_task.assert_not_awaited()
    executor.send_workflow_command.assert_awaited_once()
    assert result.status == "routed"


@pytest.mark.asyncio
async def test_create_and_execute_accepts_task_id_override_for_a2a_callers():
    """A2A pre-assigns a task id (so the JSON-RPC response can echo it). The canonical method must honour it."""
    service, mocks = _make_service()
    pre_id = uuid4()

    await service.create_and_execute_task_with_workflow(
        agent_id=uuid4(),
        description="agent-to-agent ping",
        workspace_id="ws-abc",
        user_id="user-123",
        task_id=pre_id,
        title="A2A Message Task",
        metadata_overrides={"task_source": "a2a_protocol"},
    )

    submitted = mocks["task_manager"].submit_task.await_args.args[0]
    assert submitted.id == pre_id
    assert submitted.title == "A2A Message Task"
    assert submitted.metadata["task_source"] == "a2a_protocol"
    # Canonical defaults still applied
    assert submitted.metadata["created_via"] == "api"
    assert submitted.metadata["requires_human_approval"] is False
