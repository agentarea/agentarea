"""A task's provenance -- who or what started it -- round-trips through the repository."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_tasks.domain.models import AgentTask, Task, TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository


def test_agent_task_carries_provenance_by_default_empty():
    task = AgentTask(
        title="t", description="d", query="q", user_id="u", workspace_id="w", agent_id=uuid4()
    )
    assert task.provenance == TaskProvenance()


async def test_repository_writes_provenance_columns():
    parent = uuid4()
    now = datetime.now(UTC)
    provenance = TaskProvenance(
        origin_type="trigger",
        origin_id="trig-1",
        correlation_id="corr",
        causation_id="evt",
        parent_task_id=parent,
    )
    repo = TaskRepository.__new__(TaskRepository)
    captured: dict = {}

    async def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            id=kwargs["id"],
            agent_id=kwargs["agent_id"],
            description=kwargs["description"],
            parameters={},
            status="pending",
            result=None,
            error=None,
            created_at=now,
            updated_at=now,
            started_at=None,
            completed_at=None,
            scheduled_at=None,
            execution_id=None,
            created_by="u",
            workspace_id="w",
            task_metadata={},
            origin_type="trigger",
            origin_id="trig-1",
            correlation_id="corr",
            causation_id="evt",
            parent_task_id=parent,
        )

    repo.create = AsyncMock(side_effect=create)
    stored = await repo.create_task(
        Task(
            id=uuid4(),
            agent_id=uuid4(),
            description="d",
            parameters={},
            status="pending",
            created_at=now,
            updated_at=now,
            provenance=provenance,
        )
    )
    assert captured["origin_type"] == "trigger"
    assert captured["parent_task_id"] == parent
    assert stored.provenance == provenance
