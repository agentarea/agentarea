"""The inbox lists tasks by when they called for attention.

It ordered by ``updated_at``, and the workflow writes the final status again
when a completed task's 30-minute follow-up wait expires, so a task finished
long ago jumped above newer ones while its row still read "40 minutes ago".
"""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import Task
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


async def _task(repo: TaskRepository, status: str) -> Task:
    now = datetime.now(UTC)
    return await repo.create_task(
        Task(
            id=uuid4(),
            agent_id=uuid4(),
            description="d",
            parameters={},
            status=status,
            created_at=now,
            updated_at=now,
        )
    )


async def test_a_closed_follow_up_wait_does_not_move_a_finished_task_up():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=str(uuid4())))
        older = await _task(repo, "running")
        newer = await _task(repo, "running")

        ended_older = await repo.update_status(older.id, "completed")
        assert ended_older is not None
        await repo.update_status(newer.id, "failed")
        # The older run ended first, as a real run would have.
        earlier = (datetime.now(UTC) - timedelta(minutes=40)).replace(tzinfo=None)
        await session.execute(
            update(TaskORM).where(TaskORM.id == older.id).values(completed_at=earlier)
        )

        # The follow-up wait expires: the workflow writes "completed" again.
        rewritten = await repo.update_status(older.id, "completed")
        assert rewritten is not None
        assert rewritten.completed_at is not None
        assert rewritten.completed_at.replace(tzinfo=None) == earlier

        listed = await repo.list_by_statuses(["completed", "failed"])
        assert [task.id for task in listed] == [newer.id, older.id]
    await engine.dispose()


async def test_a_task_that_starts_waiting_comes_first():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=str(uuid4())))
        finished = await _task(repo, "running")
        await repo.update_status(finished.id, "completed")
        waiting = await _task(repo, "running")
        await repo.update_status(waiting.id, "waiting_for_approval")

        listed = await repo.list_by_statuses(["completed", "waiting_for_approval"])
        assert [task.id for task in listed] == [waiting.id, finished.id]
    await engine.dispose()
