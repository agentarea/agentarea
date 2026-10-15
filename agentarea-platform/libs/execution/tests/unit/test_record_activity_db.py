"""The record activity against the migrated schema: one transaction, then the publish.

The workflow records after each model call and tool result: the log rows, the
task's status and result, and the spend and audit lines its events stand for go
in one transaction; the events are then stored and streamed. Temporal retries
the whole call, so a call that committed and then failed on the stream runs
again and must write nothing twice.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_execution.activities.agent.record import make_record_activities
from agentarea_execution.models import (
    ConversationResumeSnapshot,
    LogRow,
    RecordRequest,
    UpdateTaskStatusRequest,
)
from agentarea_tasks.application.task_event_service import TaskEventService
from agentarea_tasks.domain.models import Task, TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


class _Bodies:
    async def put(self, workspace_id: str, task_id: UUID, event_id: UUID, body: str) -> str:
        raise AssertionError("no body here is large enough to be stored by reference")

    async def get(self, ref: str) -> str:
        raise AssertionError(ref)


class _Container:
    def __init__(self, maker: async_sessionmaker) -> None:
        self._database = SimpleNamespace(async_session_factory=maker)

    def log_body_store(self) -> _Bodies:
        return _Bodies()

    async def get_task_event_service(self, user_context):
        session = self._database.async_session_factory()
        return TaskEventService(RepositoryFactory(session, user_context), None), session


class _Broker:
    def __init__(self, *, fail: bool) -> None:
        self.fail = fail
        self.streamed: list[str] = []

    async def submit(self, stream, fields, *, maxlen=None, ttl_seconds=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.streamed.append(str(decode(fields).id))
        return f"{len(self.streamed)}-0"


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    yield async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
    )
    await engine.dispose()


async def _task(maker: async_sessionmaker, workspace_id: str) -> Task:
    now = datetime.now(UTC)
    with workspace_scope(workspace_id):
        async with maker() as session:
            task = await TaskRepository(
                session, UserContext(user_id="writer", workspace_id=workspace_id)
            ).create_task(
                Task(
                    id=uuid4(),
                    agent_id=uuid4(),
                    description="d",
                    parameters={},
                    status="running",
                    created_at=now,
                    updated_at=now,
                    provenance=TaskProvenance(correlation_id="corr-7"),
                )
            )
            await session.commit()
    return task


async def test_a_record_retried_after_a_stream_failure_writes_everything_once(maker):
    workspace_id = str(uuid4())
    task = await _task(maker, workspace_id)
    paid = {
        "event_id": str(uuid4()),
        "event_type": "llm.call.completed",
        "timestamp": datetime(2026, 10, 15, 12, 0, tzinfo=UTC).isoformat(),
        "data": {"task_id": str(task.id), "agent_id": str(task.agent_id), "cost": "0.40"},
    }
    approved = {
        "event_id": str(uuid4()),
        "event_type": "approval.decided",
        "timestamp": datetime(2026, 10, 15, 12, 0, 1, tzinfo=UTC).isoformat(),
        "data": {"task_id": str(task.id), "approved": True, "approved_by": "approver"},
    }
    request = RecordRequest(
        task_id=str(task.id),
        workspace_id=workspace_id,
        user_id="writer",
        execution_id="exec-1",
        rows=[
            LogRow(seq=0, event_id=str(uuid4()), role="system", content="system", iteration=1),
            LogRow(
                seq=1,
                event_id=str(uuid4()),
                role="assistant",
                content="done",
                iteration=1,
                meta={"model_name": "m-1"},
            ),
        ],
        events_json=[json.dumps(paid), json.dumps(approved)],
        status=UpdateTaskStatusRequest(
            task_id=str(task.id),
            workspace_id=workspace_id,
            status="completed",
            result=json.dumps({"response": "done"}),
            total_cost="0.40",
            conversation_resume=ConversationResumeSnapshot(next_seq=2, current_iteration=1),
        ),
    )
    broker = _Broker(fail=True)
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=broker,
        channel_delivery_settings=None,
    )
    [record] = make_record_activities(dependencies, _Container(maker))

    try:
        with pytest.raises(ConnectionError):
            await record(request)
        broker.fail = False
        await record(request)

        async with maker() as session:
            params = {"task_id": task.id}
            rows = (
                await session.execute(
                    text(
                        "SELECT seq, execution_id, correlation_id, meta "
                        "FROM task_conversation_entries WHERE task_id = :task_id ORDER BY seq"
                    ),
                    params,
                )
            ).fetchall()
            stored_task = (
                await session.execute(
                    text("SELECT status, result, task_metadata FROM tasks WHERE id = :task_id"),
                    params,
                )
            ).one()
            costs = await session.scalar(
                text("SELECT count(*) FROM cost_entries WHERE task_id = :task_id"), params
            )
            audits = await session.scalar(
                text("SELECT count(*) FROM audit_events WHERE id = :id"),
                {"id": UUID(approved["event_id"])},
            )
            events = await session.scalar(
                text("SELECT count(*) FROM task_events WHERE task_id = :task_id"), params
            )
        assert [(r.seq, r.execution_id, r.correlation_id) for r in rows] == [
            (0, "exec-1", "corr-7"),
            (1, "exec-1", "corr-7"),
        ]
        assert rows[1].meta == {"model_name": "m-1"}
        assert stored_task.status == "completed"
        assert stored_task.result == {"response": "done", "total_cost": "0.40"}
        assert stored_task.task_metadata["conversation_resume"]["next_seq"] == 2
        assert (costs, audits, events) == (1, 1, 2)
        assert broker.streamed == [paid["event_id"], approved["event_id"]]
    finally:
        async with maker() as session:
            for table in ("cost_entries", "task_events", "task_conversation_entries"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE task_id = :task_id"), {"task_id": task.id}
                )
            await session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task.id})
            await session.commit()


async def test_a_record_for_a_task_that_is_gone_is_not_retried(maker):
    from temporalio.exceptions import ApplicationError

    workspace_id = str(uuid4())
    request = RecordRequest(
        task_id=str(uuid4()),
        workspace_id=workspace_id,
        user_id="writer",
        execution_id="exec-gone",
        rows=[],
        events_json=[],
        status=UpdateTaskStatusRequest(
            task_id=str(uuid4()), workspace_id=workspace_id, status="failed"
        ),
    )
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=_Broker(fail=False),
        channel_delivery_settings=None,
    )
    [record] = make_record_activities(dependencies, _Container(maker))

    with pytest.raises(ApplicationError) as raised:
        await record(request)
    assert raised.value.non_retryable
