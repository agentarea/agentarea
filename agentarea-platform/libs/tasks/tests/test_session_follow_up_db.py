"""A follow-up finds the live task of its trigger and session in the real tasks table."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import Task
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


async def test_only_a_live_task_of_the_same_trigger_and_session_is_found():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, agent = str(uuid4()), uuid4()
    trigger, other_trigger = str(uuid4()), str(uuid4())

    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=ws))
        now = datetime.now(UTC)

        async def stored(trigger_id, key, status="completed"):
            task_id = uuid4()
            return await repo.create_task(
                Task(
                    id=task_id,
                    agent_id=agent,
                    description="chat",
                    parameters={
                        "trigger_id": trigger_id,
                        "session": {"key": key, "continue": True},
                    },
                    status=status,
                    execution_id=f"task-{task_id}",
                    created_at=now,
                    updated_at=now,
                )
            )

        waiting = await stored(trigger, "src:42")
        await stored(trigger, "src:43")
        await stored(other_trigger, "src:42")
        await stored(trigger, "src:42", status="failed")

        found = await repo.find_active_in_session(agent, trigger, "src:42")

    assert [task.id for task in found] == [waiting.id]
    await engine.dispose()
