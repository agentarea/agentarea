"""GET …/tasks/{id}/summary reads the task row and the spend ledger, against the real schema.

The summary used to be the ``task_summary`` view over the old ``task_events``. It now
reads the run's times, answer and error from ``tasks`` and its spend from the current
``cost_entries`` lines of the run (wiki ADR-0042). Which lines count (superseded, other
currency, other workspace) is SQL a mocked session cannot check.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_api.main import app
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base import get_read_repository_factory
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.extensions.customer_pricing import get_customer_pricing
from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

STARTED = datetime(2026, 10, 7, 12, 0, 0)


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as s:
            yield s
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def workspace_id() -> str:
    return f"ws-summary-{uuid4().hex[:8]}"


@pytest.fixture
async def client(session, workspace_id):
    context = UserContext(user_id="reader", workspace_id=workspace_id)
    app.dependency_overrides[get_user_context] = lambda: context
    app.dependency_overrides[get_read_repository_factory] = lambda: RepositoryFactory(
        session, context
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_user_context, None)
        app.dependency_overrides.pop(get_read_repository_factory, None)


async def _task(session: AsyncSession, workspace_id: str, **fields) -> TaskORM:
    task = TaskORM(
        id=uuid4(),
        agent_id=uuid4(),
        description="Summarise the release",
        parameters={},
        workspace_id=workspace_id,
        created_by="reader",
        **{"status": "completed", **fields},
    )
    session.add(task)
    await session.flush()
    return task


def _line(workspace_id: str, task: TaskORM, amount: str, **fields) -> CostEntry:
    return CostEntry(
        **{
            "workspace_id": workspace_id,
            "created_by": "writer",
            "event_id": uuid4(),
            "category": CostCategory.MODEL,
            "task_id": task.id,
            "agent_id": task.agent_id,
            "subject_type": CostSubjectType.MODEL_INSTANCE,
            "subject_id": "model-1",
            "subject_name": "gpt-luna-6",
            "call_ref": None,
            "amount": Decimal(amount),
            "currency": "USD",
            "source": CostSource.TOKEN_PRICING,
            "occurred_at": datetime(2026, 10, 7, 12, 0, 30, tzinfo=UTC),
            **fields,
        }
    )


async def _record(session: AsyncSession, workspace_id: str, *lines: CostEntry) -> None:
    repo = CostEntryRepository(session, UserContext(user_id="writer", workspace_id=workspace_id))
    await repo.record(list(lines))


async def test_a_finished_run_reports_its_times_answer_error_and_current_spend(
    session, client, workspace_id
):
    task = await _task(
        session,
        workspace_id,
        status="failed",
        started_at=STARTED,
        completed_at=STARTED + timedelta(seconds=90, milliseconds=500),
        result={"response": "Half of the notes are written.", "total_cost": "0.65"},
        error="Model quota exceeded",
    )
    other_task = await _task(session, workspace_id)
    estimate = _line(workspace_id, task, "0.40", estimate=True)
    await _record(
        session,
        workspace_id,
        _line(workspace_id, task, "0.25"),
        _line(
            workspace_id,
            task,
            "0.10",
            category=CostCategory.SERVICE,
            subject_type=CostSubjectType.TOOL,
            subject_id="conn-1",
            subject_name="search",
        ),
        estimate,
        _line(workspace_id, other_task, "5"),
        _line(workspace_id, task, "9", currency="EUR"),
    )
    (estimate_id,) = (
        await session.execute(
            text("SELECT id FROM cost_entries WHERE event_id = :e"), {"e": estimate.event_id}
        )
    ).one()
    await _record(
        session,
        workspace_id,
        _line(workspace_id, task, "0.30", supersedes_id=estimate_id, source=CostSource.SETTLED),
    )
    await _record(session, "ws-elsewhere", _line("ws-elsewhere", task, "7"))

    response = await client.get(
        f"/v1/workspaces/acme/agents/{task.agent_id}/tasks/{task.id}/summary"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {
        "task_id": str(task.id),
        "agent_id": str(task.agent_id),
        "workspace_id": workspace_id,
        "status": "failed",
        "started_at": "2026-10-07T12:00:00Z",
        "ended_at": "2026-10-07T12:01:30.500000Z",
        "duration_ms": 90500.0,
        "cost": 0.65,
        "currency": get_customer_pricing().currency(),
        "final_response": "Half of the notes are written.",
        "last_error": "Model quota exceeded",
    }


async def test_a_run_not_yet_ended_has_no_end_or_duration(session, client, workspace_id):
    task = await _task(session, workspace_id, status="running", started_at=STARTED)

    response = await client.get(
        f"/v1/workspaces/acme/agents/{task.agent_id}/tasks/{task.id}/summary"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["ended_at"], body["duration_ms"], body["cost"]) == (None, None, 0.0)
    assert (body["final_response"], body["last_error"]) == (None, None)


async def test_a_task_of_another_workspace_or_agent_is_not_found(session, client, workspace_id):
    foreign = await _task(session, "ws-elsewhere")
    own = await _task(session, workspace_id)

    foreign_response = await client.get(
        f"/v1/workspaces/acme/agents/{foreign.agent_id}/tasks/{foreign.id}/summary"
    )
    wrong_agent = await client.get(f"/v1/workspaces/acme/agents/{uuid4()}/tasks/{own.id}/summary")

    assert foreign_response.status_code == 404
    assert wrong_agent.status_code == 404


async def test_status_updates_stamp_when_the_run_started_and_last_ended(session, workspace_id):
    task = await _task(session, workspace_id, status="pending")
    repo = TaskRepository(session, UserContext(user_id="writer", workspace_id=workspace_id))

    running = await repo.update_status(task.id, "running")
    assert running is not None and running.started_at is not None
    assert running.completed_at is None

    ended = await repo.update_status(task.id, "completed")
    assert ended is not None and ended.completed_at is not None

    await repo.update_status(task.id, "running")
    again = await repo.update_status(task.id, "failed")
    assert again is not None and again.completed_at is not None
    assert again.started_at == running.started_at
    assert again.completed_at >= ended.completed_at


async def test_the_task_summary_view_is_gone(session):
    assert await session.scalar(text("SELECT to_regclass('task_summary')")) is None
