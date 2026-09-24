from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.temporal_task_manager import TemporalTaskManager


@pytest.mark.asyncio
async def test_agent_workflow_disables_whole_workflow_retries() -> None:
    task = AgentTask(
        id=uuid4(),
        title="side-effecting task",
        description="run a shell command",
        query="run a shell command",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="pending",
        created_at=datetime.now(UTC),
        task_parameters={},
        metadata={},
    )
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

    await manager.submit_task(task)

    config = executor.start_workflow.await_args.kwargs["config"]
    assert config.retry_attempts == 1


@pytest.mark.asyncio
async def test_agent_workflow_starts_on_the_configured_task_queue(monkeypatch) -> None:
    import agentarea_common.config as config

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: SimpleNamespace(
            workflow=SimpleNamespace(
                NAMESPACE="default",
                TEMPORAL_URL="temporal:7233",
                QUEUE="agent-tasks-enterprise",
            )
        ),
    )
    task = AgentTask(
        id=uuid4(),
        title="queued task",
        description="say hi",
        query="say hi",
        user_id="user-1",
        workspace_id="workspace-1",
        agent_id=uuid4(),
        status="pending",
        created_at=datetime.now(UTC),
        task_parameters={},
        metadata={},
    )
    repository = MagicMock()
    manager = TemporalTaskManager(repository)
    domain_task = manager._agent_task_to_task(task)
    repository.update_status = AsyncMock(return_value=domain_task)
    repository.update_task = AsyncMock(return_value=domain_task)
    manager.temporal_executor = MagicMock()
    manager.temporal_executor.start_workflow = AsyncMock(return_value=f"task-{task.id}")

    await manager.submit_task(task)

    config_arg = manager.temporal_executor.start_workflow.await_args.kwargs["config"]
    assert config_arg.task_queue == "agent-tasks-enterprise"
