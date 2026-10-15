"""A task's log against the migrated table: one append, one transaction, one window.

``TaskLog.append`` writes the log rows, the task's outcome, its spend lines and
its audit rows in the caller's transaction; a retried append writes nothing
twice because every row carries the workflow's ``event_id``. The model's window
is the system prompt, the latest compaction and every message after it, read
in one query. Only the unique constraints, the kind check and the ordering of
the migrated table can prove that.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.domain.models import ConversationEntry, Task, TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository
from agentarea_tasks.infrastructure.task_log import (
    BODY_OFFLOAD_BYTES,
    AuditLine,
    TaskLog,
    TaskOutcome,
)
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


class _Bodies:
    def __init__(self) -> None:
        self.stored: dict[str, str] = {}

    async def put(self, workspace_id: str, task_id: UUID, event_id: UUID, body: str) -> str:
        ref = f"tasks/{workspace_id}/{task_id}/log/{event_id}"
        self.stored[ref] = body
        return ref

    async def get(self, ref: str) -> str:
        return self.stored[ref]


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


def _context(workspace_id: str) -> UserContext:
    return UserContext(user_id="log-writer", workspace_id=workspace_id)


async def _task(session: AsyncSession, workspace_id: str, **provenance) -> Task:
    now = datetime.now(UTC)
    return await TaskRepository(session, _context(workspace_id)).create_task(
        Task(
            id=uuid4(),
            agent_id=uuid4(),
            description="d",
            parameters={},
            status="running",
            created_at=now,
            updated_at=now,
            metadata={"kept": True},
            provenance=TaskProvenance(**provenance),
        )
    )


def _row(seq: int, content: str, **fields) -> ConversationEntry:
    return ConversationEntry(
        seq=seq,
        event_id=fields.pop("event_id", uuid4()),
        role=fields.pop("role", "user"),
        content=content,
        **fields,
    )


async def test_append_carries_the_task_chain_and_writes_each_event_once(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id, correlation_id="corr-1", causation_id="cause-1")
    log = TaskLog(session, _context(workspace_id), _Bodies())
    rows = [
        _row(0, "system", role="system", iteration=1),
        _row(1, "the task", iteration=1),
        _row(2, "answer", role="assistant", iteration=1, meta={"model_name": "m-1"}),
    ]

    await log.append(task.id, rows, execution_id="exec-1")
    await log.append(task.id, rows, execution_id="exec-1")

    stored = (
        await session.execute(
            text(
                "SELECT seq, event_id, execution_id, iteration, meta, correlation_id, "
                "causation_id FROM task_conversation_entries WHERE task_id = :task_id "
                "ORDER BY seq"
            ),
            {"task_id": task.id},
        )
    ).fetchall()
    assert [(r.seq, r.event_id) for r in stored] == [(row.seq, row.event_id) for row in rows]
    assert {(r.execution_id, r.iteration, r.correlation_id, r.causation_id) for r in stored} == {
        ("exec-1", 1, "corr-1", "cause-1")
    }
    assert stored[2].meta == {"model_name": "m-1"}


async def test_append_writes_outcome_costs_and_audit_in_the_callers_transaction(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id)
    await session.commit()
    log = TaskLog(session, _context(workspace_id), _Bodies())
    event_id = uuid4()
    cost = CostEntry(
        workspace_id=workspace_id,
        created_by="log-writer",
        event_id=event_id,
        category=CostCategory.MODEL,
        task_id=task.id,
        agent_id=task.agent_id,
        subject_type=CostSubjectType.MODEL_INSTANCE,
        subject_id="model-1",
        subject_name="m-1",
        call_ref=None,
        amount=Decimal("0.25"),
        currency="USD",
        source=CostSource.TOKEN_PRICING,
        occurred_at=datetime.now(UTC),
    )
    audit = AuditLine(
        event_id=event_id,
        action="approval.approved",
        task_id=str(task.id),
        actor_type="user",
        actor_id="approver",
        event_metadata={"decision": "approved"},
    )
    try:
        await log.append(
            task.id,
            [_row(0, "done", role="assistant")],
            outcome=TaskOutcome(
                status="completed",
                result={"response": "done"},
                metadata_patch={"conversation_resume": {"next_seq": 1}},
            ),
            costs=[cost],
            audits=[audit],
        )

        stored = await TaskRepository(session, _context(workspace_id)).get_task(task.id)
        assert stored is not None
        assert stored.status == "completed"
        assert stored.result == {"response": "done"}
        assert stored.metadata == {"kept": True, "conversation_resume": {"next_seq": 1}}
        written = await _counts(session, task.id, event_id)
        assert written == (1, 1, 1)

        await session.rollback()

        assert await _counts(session, task.id, event_id) == (0, 0, 0)
        reverted = await TaskRepository(session, _context(workspace_id)).get_task(task.id)
        assert reverted is not None and reverted.status == "running"
    finally:
        await session.rollback()
        await session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task.id})
        await session.commit()


async def _counts(session: AsyncSession, task_id: UUID, event_id: UUID) -> tuple[int, int, int]:
    return (
        await session.scalar(
            text("SELECT count(*) FROM task_conversation_entries WHERE task_id = :t"),
            {"t": task_id},
        ),
        await session.scalar(
            text("SELECT count(*) FROM cost_entries WHERE event_id = :e"), {"e": event_id}
        ),
        await session.scalar(
            text("SELECT count(*) FROM audit_events WHERE id = :e"), {"e": event_id}
        ),
    )


async def test_the_window_is_the_system_prompt_the_latest_compaction_and_what_follows(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id)
    log = TaskLog(session, _context(workspace_id), _Bodies())
    skill = "<skill_content>Use the ledger.</skill_content>"
    await log.append(
        task.id,
        [
            _row(0, "system", role="system"),
            _row(1, "the task"),
            _row(2, "early answer", role="assistant"),
            _row(3, "first summary", kind="compaction"),
            _row(4, "more"),
            _row(5, "", kind="event", role="event", name="model.changed", meta={"to": "m-2"}),
            _row(6, "second summary", kind="compaction", meta={"skills": [skill]}),
            _row(7, "after", role="assistant"),
            _row(8, "", kind="event", role="event", name="approval.request", meta={}),
            _row(9, "next question"),
            _row(10, "beyond the bound"),
        ],
    )

    window = await log.window(task.id, end_seq=10)

    assert [entry.seq for entry in window] == [0, 6, 7, 9]
    assert window[1].as_message() == {
        "role": "user",
        "content": f"second summary\n\n{skill}",
    }


async def test_the_window_leaves_out_tool_calls_the_log_never_answered(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id)
    log = TaskLog(session, _context(workspace_id), _Bodies())
    call = {"id": "c1", "type": "function", "function": {"name": "shell", "arguments": "{}"}}
    await log.append(
        task.id,
        [
            _row(0, "system", role="system"),
            _row(1, "the task"),
            _row(2, "", role="assistant", tool_calls=[call]),
            _row(3, "a retry"),
        ],
    )

    window = await log.window(task.id, end_seq=4)

    assert [entry.seq for entry in window] == [0, 1, 3]


async def test_a_body_over_the_threshold_is_stored_by_reference_and_read_back(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id)
    bodies = _Bodies()
    log = TaskLog(session, _context(workspace_id), bodies)
    large = "x" * (BODY_OFFLOAD_BYTES + 1)
    row = _row(1, large)

    await log.append(task.id, [_row(0, "system", role="system"), row])

    stored = (
        await session.execute(
            text(
                "SELECT content, body_ref FROM task_conversation_entries "
                "WHERE task_id = :t AND seq = 1"
            ),
            {"t": task.id},
        )
    ).one()
    assert stored.content == ""
    assert bodies.stored[stored.body_ref] == large
    window = await log.window(task.id, end_seq=2)
    assert window[1].content == large


async def test_a_kind_outside_message_compaction_and_event_is_refused(session):
    workspace_id = str(uuid4())
    task = await _task(session, workspace_id)
    log = TaskLog(session, _context(workspace_id), _Bodies())

    with pytest.raises(IntegrityError):
        await log.append(task.id, [_row(0, "old", kind="summary")])
