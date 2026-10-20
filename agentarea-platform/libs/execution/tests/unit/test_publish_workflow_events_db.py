"""A retried workflow-event batch against the migrated ``task_events`` table.

Temporal retries the publish activity as a whole batch, so a batch that
committed and then failed on the stream runs again. Only the real primary key
shows the retry leaves one row per event, stored under the workflow's id and
timestamp, and that the stream carries the same id the read side dedups by.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.audit import AuditService
from agentarea_common.base import RepositoryFactory
from agentarea_common.base.tenant_scope import tenant_scoped_session_class
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_execution.activities.agent.events import make_events_activities
from agentarea_execution.models import WorkflowEventsRequest
from agentarea_tasks.application.task_event_service import TaskEventService
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


class _Container:
    def __init__(self, maker: async_sessionmaker) -> None:
        self._database = SimpleNamespace(async_session_factory=maker)

    async def get_task_event_service(self, user_context):
        session = self._database.async_session_factory()
        return TaskEventService(RepositoryFactory(session, user_context), None), session

    async def get_audit_service(self, user_context):
        session = self._database.async_session_factory()
        return AuditService(session, user_context), session


class _Broker:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.streamed: list[tuple[str, str]] = []

    async def submit(self, stream, fields, *, retention):
        if self.fail:
            raise ConnectionError("redis down")
        event = decode(fields)
        self.streamed.append((str(event.id), event.time.isoformat()))
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


async def test_a_batch_retried_after_a_stream_failure_stores_each_event_once(maker):
    workspace_id, task_id = str(uuid4()), str(uuid4())
    start = datetime(2026, 9, 29, 12, 0, 0, 1, tzinfo=UTC)
    events = [
        {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "timestamp": (start + timedelta(microseconds=offset)).isoformat(),
            "data": {"task_id": task_id, "n": offset},
        }
        for offset, event_type in enumerate(["tool.call", "llm.call.completed"])
    ]
    request = WorkflowEventsRequest(
        events_json=[json.dumps(e) for e in events], workspace_id=workspace_id, user_id="writer"
    )
    broker = _Broker(fail=True)
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=broker,
    )
    [publish] = make_events_activities(dependencies, _Container(maker))

    try:
        with pytest.raises(ConnectionError):
            await publish(request)
        broker.fail = False
        await publish(request)

        async with maker() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, timestamp FROM task_events "
                        "WHERE task_id = :task_id ORDER BY timestamp"
                    ),
                    {"task_id": task_id},
                )
            ).fetchall()
        stored = [(str(row.id), row.timestamp.isoformat()) for row in rows]
        assert stored == [(e["event_id"], e["timestamp"]) for e in events]
        assert broker.streamed == stored
    finally:
        async with maker() as session:
            await session.execute(
                text("DELETE FROM task_events WHERE task_id = :task_id"), {"task_id": task_id}
            )
            await session.commit()


async def test_a_retried_batch_records_each_paid_line_once(maker):
    workspace_id, task_id, agent_id = str(uuid4()), str(uuid4()), str(uuid4())
    at = datetime(2026, 10, 8, 12, 0, tzinfo=UTC).isoformat()
    events = [
        {
            "event_id": str(uuid4()),
            "event_type": "llm.call.completed",
            "timestamp": at,
            "data": {"task_id": task_id, "agent_id": agent_id, "cost": "0.40"},
        },
        {
            "event_id": str(uuid4()),
            "event_type": "tool.result",
            "timestamp": at,
            "data": {
                "task_id": task_id,
                "agent_id": agent_id,
                "tool_name": "fetch_report",
                "service_cost": "0.10",
            },
        },
    ]
    request = WorkflowEventsRequest(
        events_json=[json.dumps(e) for e in events], workspace_id=workspace_id, user_id="writer"
    )
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=_Broker(),
    )
    [publish] = make_events_activities(dependencies, _Container(maker))

    try:
        await publish(request)
        await publish(request)

        async with maker() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT category, amount, currency, agent_id FROM cost_entries "
                        "WHERE task_id = :task_id ORDER BY category"
                    ),
                    {"task_id": task_id},
                )
            ).fetchall()
        assert [(r.category, str(r.amount), r.currency, str(r.agent_id)) for r in rows] == [
            ("model", "0.400000000000", "USD", agent_id),
            ("service", "0.100000000000", "USD", agent_id),
        ]
    finally:
        async with maker() as session:
            for table in ("cost_entries", "task_events"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE task_id = :task_id"), {"task_id": task_id}
                )
            await session.commit()
