"""A follow-up message reaches a running task, or continues a completed one whose workflow closed."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from agentarea_governance.domain.policies import (
    BudgetPolicy,
    EffectivePolicy,
    ExecutionLimitsPolicy,
    TokenPolicy,
)
from agentarea_tasks.domain.exceptions import RunStillClosingError
from agentarea_tasks.domain.interfaces import BaseTaskManager
from agentarea_tasks.domain.models import ConversationEntry, Task
from agentarea_tasks.infrastructure.repository import TaskConversationRepository, TaskRepository
from agentarea_tasks.task_service import TaskService

SNAPSHOT = {
    "head_seqs": [0],
    "tail_start": 1,
    "next_seq": 4,
    "current_iteration": 1,
    "tool_calls_used": 1,
    "tokens_used": 120,
    "last_prompt_tokens": 100,
}


class _Tasks:
    def __init__(self, task: Task):
        self.task = task

    async def get_task(self, task_id: UUID) -> Task | None:
        return self.task if task_id == self.task.id else None

    async def merge_metadata(self, task_id: UUID, patch: dict[str, Any]) -> bool:
        self.task.metadata = {**(self.task.metadata or {}), **patch}
        return True

    async def sum_spend_mtd(self) -> float:
        return 0.0

    async def sum_task_llm_spend(self, task_id: UUID) -> Decimal:
        return Decimal("0.0080") if task_id == self.task.id else Decimal(0)


class _Conversation:
    def __init__(self, entries: list[ConversationEntry], *, logged_up_to: int | None = None):
        self.entries = entries
        self.written: list[ConversationEntry] = []
        self.logged_up_to = logged_up_to

    async def read_all(self, _task_id: UUID) -> list[ConversationEntry]:
        return list(self.entries)

    async def next_seq(self, _task_id: UUID) -> int:
        if self.logged_up_to is not None:
            return self.logged_up_to
        return max((entry.seq for entry in self.entries), default=-1) + 1

    async def has_messages_from(self, _task_id: UUID, seq: int) -> bool:
        return any(entry.seq >= seq and entry.kind != "event" for entry in self.entries)

    async def write(self, _task_id: UUID, entries: list[ConversationEntry]) -> None:
        self.written.extend(entries)


class _Workflows:
    def __init__(self, *, running: bool, execution_status: str):
        self.running = running
        self.execution_status = execution_status
        self.signals: list[tuple[str, str, dict[str, Any]]] = []

    async def send_workflow_command(
        self, execution_id: str, command: str, payload: dict[str, Any]
    ) -> bool:
        if not self.running:
            return False
        self.signals.append((execution_id, command, payload))
        return True

    async def get_workflow_status(self, _execution_id: str) -> dict[str, Any]:
        return {"status": self.execution_status, "execution_status": self.execution_status}


class _Engine(BaseTaskManager):
    supports_resume = True

    def __init__(self):
        self.resumed: list[tuple[Any, Any, str | None]] = []

    async def resume_task(self, task, resume, message):
        self.resumed.append((task, resume, message))
        return task

    async def submit_task(self, task):
        raise AssertionError("a follow-up never creates a task")

    async def get_task(self, task_id):
        raise NotImplementedError

    async def cancel_task(self, task_id):
        raise NotImplementedError

    async def list_tasks(self, agent_id=None, user_id=None, workspace_id=None, limit=100, offset=0):
        raise NotImplementedError

    async def get_task_status(self, task_id):
        raise NotImplementedError

    async def get_task_result(self, task_id):
        raise NotImplementedError


def _task(status: str, metadata: dict[str, Any], result: dict[str, Any] | None = None) -> Task:
    task_id = uuid4()
    now = datetime.now(UTC)
    return Task(
        id=task_id,
        agent_id=uuid4(),
        description="List the files",
        parameters={},
        status=status,
        execution_id=f"task-{task_id}",
        user_id="user-1",
        workspace_id="ws-1",
        created_at=now,
        updated_at=now,
        result=result,
        metadata={
            "governance_snapshot": {"requested_policy": {}, "revision": 1},
            **metadata,
        },
    )


def _service(task: Task, workflows: _Workflows, conversation: _Conversation | None = None):
    tasks = _Tasks(task)
    conversation = conversation or _Conversation([], logged_up_to=SNAPSHOT["next_seq"])
    repositories = {TaskRepository: tasks, TaskConversationRepository: conversation}
    factory = MagicMock()
    factory.create_repository = MagicMock(
        side_effect=lambda cls: repositories.get(cls, MagicMock())
    )
    resolver = AsyncMock()
    resolver.resolve.return_value = EffectivePolicy(
        budget=BudgetPolicy(run_budget_usd=Decimal("50.00")),
        tokens=TokenPolicy(max_tokens=20_000_000, max_tokens_per_call=100_000),
        execution=ExecutionLimitsPolicy(
            max_model_turns=100, max_tool_calls_per_turn=10, max_tool_calls_total=1000
        ),
    )
    engine = _Engine()
    service = TaskService(
        repository_factory=factory,
        event_broker=AsyncMock(),
        task_manager=engine,
        policy_resolver=resolver,
        workflow_service=workflows,
    )
    return service, engine, conversation


@pytest.mark.asyncio
async def test_running_task_receives_the_message_as_a_signal():
    task = _task("completed", {"conversation_resume": SNAPSHOT})
    workflows = _Workflows(running=True, execution_status="running")
    service, engine, _ = _service(task, workflows)

    assert await service.queue_follow_up(task.id, "And then?") is True

    assert workflows.signals == [(task.execution_id, "queue_message", {"message": "And then?"})]
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_completed_task_with_closed_workflow_resumes_from_its_snapshot():
    task = _task(
        "completed",
        {"conversation_resume": SNAPSHOT},
        result={"response": "Done", "total_cost": "0.0300", "own_cost": "0.0100"},
    )
    service, engine, conversation = _service(
        task, _Workflows(running=False, execution_status="completed")
    )

    assert await service.queue_follow_up(task.id, "And then?") is True

    [(resumed_task, resume, message)] = engine.resumed
    assert message == "And then?"
    assert resume.snapshot.model_dump() == SNAPSHOT
    assert resume.total_cost == Decimal("0.03")
    assert resume.own_cost == Decimal("0.01")
    assert resume.llm_cost == Decimal("0.008")
    assert resume.system_prompt_missing is False
    assert conversation.written == []
    # The new run gets today's policy, recorded as the task's next revision.
    assert resumed_task.effective_policy["budget"]["run_budget_usd"] == "50.00"
    assert task.metadata["governance_snapshot"]["revision"] == 2


@pytest.mark.asyncio
async def test_task_without_snapshot_is_rebuilt_from_its_log():
    task = _task("completed", {}, result={"response": "Here they are"})
    log = _Conversation(
        [
            ConversationEntry(seq=0, role="system", content="Instructions"),
            ConversationEntry(seq=1, role="user", content="List the files"),
        ]
    )
    service, engine, _ = _service(task, _Workflows(running=False, execution_status="unknown"), log)

    assert await service.queue_follow_up(task.id, "And then?") is True

    [(_, resume, _)] = engine.resumed
    assert [(entry.seq, entry.role, entry.content) for entry in log.written] == [
        (2, "assistant", "Here they are")
    ]
    # The resumed run reads its window from the log; a rebuilt snapshot sets no cursors.
    assert resume.snapshot.head_seqs == []
    assert resume.snapshot.next_seq == 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "metadata"),
    [
        ("blocked", {"conversation_resume": SNAPSHOT}),
        ("running", {"conversation_resume": SNAPSHOT}),
        ("completed", {"conversation_resume": SNAPSHOT, "created_via": "agent_delegation"}),
    ],
)
async def test_only_a_closed_user_conversation_resumes(status, metadata):
    task = _task(status, metadata)
    service, engine, _ = _service(task, _Workflows(running=False, execution_status="completed"))

    assert await service.queue_follow_up(task.id, "And then?") is False
    assert engine.resumed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["cancelled", "failed"])
async def test_stopped_or_failed_task_continues_its_conversation(status):
    task = _task(status, {"conversation_resume": SNAPSHOT}, result={"total_cost": "0.0200"})
    workflows = _Workflows(running=False, execution_status=status)
    service, engine, conversation = _service(task, workflows)

    assert await service.queue_follow_up(task.id, "Carry on") is True

    [(_, resume, message)] = engine.resumed
    assert message == "Carry on"
    assert resume.snapshot.model_dump() == SNAPSHOT
    assert resume.total_cost == Decimal("0.02")
    assert resume.retry is False
    assert conversation.written == []


@pytest.mark.asyncio
async def test_stopped_task_still_finishing_is_not_signalled():
    """A stopping run would drop a signalled message; the caller is told to try again."""
    task = _task("cancelled", {"conversation_resume": SNAPSHOT})
    workflows = _Workflows(running=True, execution_status="running")
    service, engine, _ = _service(task, workflows)

    with pytest.raises(RunStillClosingError):
        await service.queue_follow_up(task.id, "Carry on")

    assert workflows.signals == []
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_snapshot_behind_the_log_is_rebuilt_instead_of_overwriting_it():
    task = _task("failed", {"conversation_resume": SNAPSHOT}, result={})
    log = _Conversation(
        [
            ConversationEntry(seq=0, role="system", content="Instructions"),
            ConversationEntry(seq=1, role="user", content="List the files"),
            ConversationEntry(seq=2, role="assistant", content="Two files."),
            ConversationEntry(seq=3, role="user", content="Which is newer?"),
            ConversationEntry(seq=4, role="assistant", content="The second."),
            ConversationEntry(seq=5, role="user", content="Delete it"),
        ]
    )
    service, engine, _ = _service(task, _Workflows(running=False, execution_status="failed"), log)

    assert await service.queue_follow_up(task.id, "Go on") is True

    [(_, resume, _)] = engine.resumed
    assert resume.snapshot.next_seq == 6
    assert log.written == []


@pytest.mark.asyncio
async def test_closing_events_after_the_snapshot_resume_it_after_them():
    task = _task("completed", {"conversation_resume": SNAPSHOT}, result={"response": "Done"})
    log = _Conversation(
        [
            ConversationEntry(seq=3, role="assistant", content="Done"),
            ConversationEntry(seq=4, kind="event", role="event", content="", name="task.completed"),
            ConversationEntry(
                seq=5, kind="event", role="event", content="", name="execution.finished"
            ),
        ]
    )
    service, engine, _ = _service(
        task, _Workflows(running=False, execution_status="completed"), log
    )

    assert await service.queue_follow_up(task.id, "And then?") is True

    [(_, resume, _)] = engine.resumed
    assert resume.snapshot.model_dump() == {**SNAPSHOT, "next_seq": 6}
    assert log.written == []


@pytest.mark.asyncio
async def test_retry_reruns_a_failed_turn_without_a_new_message():
    task = _task("failed", {"conversation_resume": SNAPSHOT}, result={"total_cost": "0.0100"})
    workflows = _Workflows(running=False, execution_status="failed")
    service, engine, _ = _service(task, workflows)

    assert await service.retry_last_turn(task.id) is True

    [(resumed_task, resume, message)] = engine.resumed
    assert message is None
    assert resume.retry is True
    assert resume.snapshot.model_dump() == SNAPSHOT
    assert resume.total_cost == Decimal("0.01")
    assert workflows.signals == []
    assert resumed_task.effective_policy["budget"]["run_budget_usd"] == "50.00"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "execution_status"),
    [("completed", "completed"), ("cancelled", "cancelled"), ("blocked", "completed")],
)
async def test_retry_needs_a_failed_task_whose_run_closed(status, execution_status):
    task = _task(status, {"conversation_resume": SNAPSHOT})
    service, engine, _ = _service(
        task, _Workflows(running=False, execution_status=execution_status)
    )

    assert await service.retry_last_turn(task.id) is False
    assert engine.resumed == []


@pytest.mark.asyncio
async def test_unreachable_running_workflow_is_not_restarted():
    task = _task("completed", {"conversation_resume": SNAPSHOT})
    service, engine, _ = _service(task, _Workflows(running=False, execution_status="running"))

    assert await service.queue_follow_up(task.id, "And then?") is False
    assert engine.resumed == []
