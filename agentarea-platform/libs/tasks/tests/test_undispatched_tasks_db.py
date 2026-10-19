"""Tasks left pending with no workflow are started, each in its own workspace.

The search spans every workspace under the ENFORCE tenant scope; each start
runs bound to the task's workspace. Fresh tasks, tasks with an execution,
trigger tasks (their redelivery owns the restart) and tasks past the horizon
are left alone.

Set TASKS_TEST_DATABASE_URL to a postgresql+asyncpg URL for a disposable,
already-migrated database.
"""

import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import (
    current_workspace_scope,
    tenant_scoped_session_class,
    unscoped,
    workspace_scope,
)
from agentarea_common.config.database import TenantScopeMode
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.undispatched_tasks import STALE_AFTER, start_undispatched_tasks
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

# Far from any row another suite leaves behind, so the cross-workspace search sees only these.
NOW = datetime(2100, 1, 1)
STALE = NOW - STALE_AFTER - timedelta(seconds=30)
SNAPSHOT = {"governance_snapshot": {"effective_policy": {"budget": {}}, "revision": 1}}


class Engine:
    supports_scheduling = True

    def __init__(self, refuse: set[UUID] | None = None):
        self.started: list[tuple[UUID, str | None]] = []
        self._refuse = refuse or set()

    async def submit_task(self, task):
        if task.id in self._refuse:
            raise ConnectionError("temporal unavailable")
        self.started.append((task.id, current_workspace_scope()))
        return task


@pytest.fixture
async def maker():
    engine = create_async_engine(TEST_DATABASE_URL)
    factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    yield factory
    async with factory() as session:
        with unscoped("the test removes the rows it seeded in several workspaces"):
            await session.execute(
                delete(TaskORM).where(TaskORM.created_at >= NOW - timedelta(days=30))
            )
        await session.commit()
    await engine.dispose()


async def _seed(maker, workspace_id: str, **overrides) -> UUID:
    task_id = uuid4()
    row = {
        "id": task_id,
        "agent_id": uuid4(),
        "description": "go",
        "parameters": {},
        "status": "pending",
        "created_by": "owner",
        "workspace_id": workspace_id,
        "task_metadata": SNAPSHOT,
        "created_at": STALE,
        "updated_at": STALE,
        **overrides,
    }
    with workspace_scope(workspace_id):
        async with maker() as session:
            session.add(TaskORM(**row))
            await session.commit()
    return task_id


def _service_for(engine: Engine):
    def task_service_for(session: AsyncSession, user_context: UserContext) -> TaskService:
        return TaskService(
            repository_factory=RepositoryFactory(session, user_context),
            event_broker=AsyncMock(),
            task_manager=engine,
            policy_resolver=AsyncMock(),
        )

    return task_service_for


async def test_stranded_tasks_of_every_workspace_start_in_their_own(maker):
    ws_a, ws_b = str(uuid4()), str(uuid4())
    stranded_a = await _seed(maker, ws_a)
    stranded_b = await _seed(maker, ws_b)
    engine = Engine()

    started = await start_undispatched_tasks(maker, _service_for(engine), now=NOW)

    assert started == 2
    assert sorted(engine.started) == sorted([(stranded_a, ws_a), (stranded_b, ws_b)])


@pytest.mark.parametrize(
    "overrides",
    [
        {"created_at": NOW - STALE_AFTER + timedelta(seconds=30)},
        {"execution_id": "task-x"},
        {"status": "running"},
        {"status": "failed"},
        {"origin_type": "trigger"},
        {"created_at": NOW - timedelta(days=2)},
    ],
    ids=["fresh", "has-execution", "running", "failed", "trigger", "past-horizon"],
)
async def test_tasks_that_are_not_stranded_are_left_alone(maker, overrides):
    await _seed(maker, str(uuid4()), **overrides)
    engine = Engine()

    assert await start_undispatched_tasks(maker, _service_for(engine), now=NOW) == 0
    assert engine.started == []


async def test_a_start_that_fails_leaves_the_task_pending_and_the_rest_start(maker):
    ws = str(uuid4())
    refused = await _seed(maker, ws)
    other = await _seed(maker, ws)
    engine = Engine(refuse={refused})

    assert await start_undispatched_tasks(maker, _service_for(engine), now=NOW) == 1
    assert engine.started == [(other, ws)]
    with workspace_scope(ws):
        async with maker() as session:
            status = await session.scalar(select(TaskORM.status).where(TaskORM.id == refused))
    assert status == "pending"
