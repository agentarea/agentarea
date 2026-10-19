"""Test that follow-up messages route to existing active workflows
instead of creating new tasks via TaskService.route_or_submit_task()."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_tasks.domain.models import AgentTask, Task


def _make_agent_task(agent_id, chat_id, query="hello"):
    """Create an AgentTask in a continued session."""
    return AgentTask(
        title="Test",
        description=query,
        query=query,
        user_id="user-1",
        workspace_id="ws-1",
        agent_id=agent_id,
        task_parameters={
            "trigger_id": "trg-1",
            "session": {"key": str(chat_id), "continue": True},
        },
    )


def _make_domain_task(agent_id, chat_id, status="running", execution_id=None):
    """Create a Task domain model matching an active workflow."""
    task_id = uuid4()
    now = datetime.now(UTC)
    return Task(
        id=task_id,
        agent_id=agent_id,
        description="previous task",
        parameters={"trigger_id": "trg-1", "session": {"key": str(chat_id), "continue": True}},
        status=status,
        execution_id=execution_id or f"task-{task_id}",
        user_id="user-1",
        workspace_id="ws-1",
        created_at=now,
        updated_at=now,
    )


def _make_task_service(
    candidates: list[Task] | None = None,
    signal_side_effect=None,
):
    """Build a TaskService with mocked dependencies for routing tests."""
    from agentarea_tasks.task_service import TaskService

    # Mock repository factory
    repo_factory = MagicMock()
    task_repo = AsyncMock()
    task_repo.find_active_in_session = AsyncMock(return_value=candidates or [])
    repo_factory.create_repository = MagicMock(return_value=task_repo)

    # Mock event broker
    event_broker = AsyncMock()

    # Mock task manager with temporal_executor
    task_manager = AsyncMock()
    task_manager.temporal_executor = AsyncMock()
    if signal_side_effect:
        task_manager.temporal_executor.send_workflow_command = AsyncMock(
            side_effect=signal_side_effect
        )
    else:
        task_manager.temporal_executor.send_workflow_command = AsyncMock(return_value=True)

    policy_resolver = AsyncMock()
    policy_resolver.resolve.return_value = EffectivePolicy(
        budget=BudgetPolicy(run_budget_usd="50.00"),
        tokens=TokenPolicy(max_tokens=20_000_000, max_tokens_per_call=100_000),
        execution=ExecutionLimitsPolicy(
            max_model_turns=100,
            max_tool_calls_per_turn=10,
            max_tool_calls_total=1000,
        ),
    )
    service = TaskService(
        repository_factory=repo_factory,
        event_broker=event_broker,
        task_manager=task_manager,
        policy_resolver=policy_resolver,
    )
    # Skip agent validation and mock create_task to return the task as-is
    service.agent_repository = None
    service.create_task = AsyncMock(side_effect=lambda t: t)
    # Make task_manager.submit_task return its input by default
    task_manager.submit_task = AsyncMock(side_effect=lambda t: t)

    return service, task_manager, task_repo


class TestRouteOrSubmitTask:
    """Tests for TaskService.route_or_submit_task() — the unified routing point."""

    @pytest.mark.asyncio
    async def test_routes_to_existing_workflow(self):
        """Message with matching chat_id should signal existing workflow, not create new task."""
        agent_id = uuid4()
        chat_id = "12345"
        active_task = _make_domain_task(agent_id, chat_id, "running")

        service, task_manager, _task_repo = _make_task_service(candidates=[active_task])

        task = _make_agent_task(agent_id, chat_id, query="follow-up question")
        result = await service.route_or_submit_task(task)

        assert result.status == "routed"
        assert result.execution_id == active_task.execution_id
        task_manager.temporal_executor.send_workflow_command.assert_called_once_with(
            active_task.execution_id,
            "queue_message",
            {"message": "follow-up question"},
        )
        # submit_task should NOT be called
        task_manager.submit_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_creates_new_task_when_no_active_workflow(self):
        """No active workflow => falls through to submit_task."""
        agent_id = uuid4()

        service, task_manager, task_repo = _make_task_service(candidates=[])

        task = _make_agent_task(agent_id, "99999", query="first message")
        await service.route_or_submit_task(task)

        task_repo.find_active_in_session.assert_called_once()
        task_manager.submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_new_task_when_signal_returns_false(self):
        """If send_workflow_command returns False, fall through to submit_task."""
        agent_id = uuid4()
        chat_id = "12345"
        active_task = _make_domain_task(agent_id, chat_id)

        service, task_manager, _task_repo = _make_task_service(
            candidates=[active_task],
            signal_side_effect=lambda *a, **kw: False,
        )

        task = _make_agent_task(agent_id, chat_id, query="retry message")
        await service.route_or_submit_task(task)

        # Signal was attempted
        task_manager.temporal_executor.send_workflow_command.assert_called_once()
        # Fell through to new task
        task_manager.submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_different_chat_ids_dont_cross_route(self):
        """Messages from different chat_ids should not route to each other."""
        agent_id = uuid4()

        # No candidates returned for chat 222
        service, task_manager, task_repo = _make_task_service(candidates=[])

        task = _make_agent_task(agent_id, "222", query="hello")
        await service.route_or_submit_task(task)

        task_repo.find_active_in_session.assert_called_once_with(agent_id, "trg-1", "222")
        task_manager.temporal_executor.send_workflow_command.assert_not_called()
        task_manager.submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_session_skips_routing(self):
        """Tasks without a session go straight to submit_task."""
        agent_id = uuid4()

        service, task_manager, task_repo = _make_task_service()

        task = AgentTask(
            title="API task",
            description="do something",
            query="do something",
            user_id="user-1",
            workspace_id="ws-1",
            agent_id=agent_id,
            task_parameters={},
        )
        await service.route_or_submit_task(task)

        # Should not even query for candidates
        task_repo.find_active_in_session.assert_not_called()
        task_manager.submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_session_that_does_not_continue_starts_its_own_task(self):
        agent_id = uuid4()
        service, task_manager, task_repo = _make_task_service()
        task = _make_agent_task(agent_id, "12345")
        task.task_parameters["session"]["continue"] = False

        await service.route_or_submit_task(task)

        task_repo.find_active_in_session.assert_not_called()
        task_manager.submit_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_temporal_executor_skips_routing(self):
        """If task_manager has no temporal_executor, skip routing."""
        agent_id = uuid4()

        service, task_manager, task_repo = _make_task_service()
        del task_manager.temporal_executor  # Simulate DirectTaskManager

        task = _make_agent_task(agent_id, "12345", query="hello")
        await service.route_or_submit_task(task)

        task_repo.find_active_in_session.assert_not_called()
        task_manager.submit_task.assert_called_once()
