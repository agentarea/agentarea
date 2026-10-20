"""A task's provenance -- who or what started it -- round-trips through the repository."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_common.auth.context import Subject, UserContext
from agentarea_common.auth.credential import Credential
from agentarea_tasks.domain.models import AgentTask, Task, TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository


def test_agent_task_carries_provenance_by_default_empty():
    task = AgentTask(
        title="t", description="d", query="q", user_id="u", workspace_id="w", agent_id=uuid4()
    )
    assert task.provenance == TaskProvenance()


async def test_repository_writes_provenance_columns():
    parent = uuid4()
    definition = uuid4()
    now = datetime.now(UTC)
    provenance = TaskProvenance(
        origin_type="trigger",
        origin_id="trig-1",
        correlation_id="corr",
        causation_id="evt",
        parent_task_id=parent,
        depth=2,
        task_definition_id=definition,
        source_identity="user:alice",
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
            depth=kwargs["depth"],
            task_definition_id=kwargs["task_definition_id"],
            source_identity=kwargs["source_identity"],
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
    assert captured["depth"] == 2
    assert captured["task_definition_id"] == definition
    assert captured["source_identity"] == "user:alice"
    assert stored.provenance == provenance


def test_a_person_starting_a_run_is_its_source():
    person = UserContext(user_id="alice", workspace_id="w")
    by_key = UserContext(
        user_id="alice", workspace_id="w", credential=Credential(kind="api_key", key_id="k")
    )

    assert TaskProvenance.started_by_caller(person) == TaskProvenance(
        origin_type="user", origin_id="alice", source_identity="user:alice"
    )
    assert TaskProvenance.started_by_caller(by_key).origin_type == "api"


def test_an_agent_starting_a_run_is_recorded_as_the_agent_and_no_person_narrows_it():
    """The person the agent's own run is attributed to did not start this one."""
    in_run = UserContext(user_id="alice", workspace_id="w", subject=Subject(kind="agent", id="a-7"))

    provenance = TaskProvenance.started_by_caller(in_run)

    assert (provenance.origin_type, provenance.origin_id) == ("agent", "a-7")
    assert provenance.source_user_id is None
