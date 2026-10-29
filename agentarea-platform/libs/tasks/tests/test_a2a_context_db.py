"""An A2A message's contextId finds the newest task of its agent in the real tasks table."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import Task
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


async def test_the_newest_task_of_the_agent_in_the_context_is_found():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, agent, other_agent = str(uuid4()), uuid4(), uuid4()
    context = f"ctx-{uuid4()}"

    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=ws))
        start = datetime.now(UTC)

        async def stored(agent_id, context_id, minutes):
            at = start + timedelta(minutes=minutes)
            return await repo.create_task(
                Task(
                    id=uuid4(),
                    agent_id=agent_id,
                    description="chat",
                    parameters={},
                    status="completed",
                    metadata={"a2a_context_id": context_id} if context_id else {},
                    created_at=at,
                    updated_at=at,
                )
            )

        await stored(agent, context, 0)
        newest = await stored(agent, context, 1)
        await stored(agent, f"ctx-{uuid4()}", 2)
        await stored(agent, None, 3)
        await stored(other_agent, context, 4)

        found = await repo.latest_in_a2a_context(agent, context)
        missing = await repo.latest_in_a2a_context(agent, f"ctx-{uuid4()}")

    assert found is not None and found.id == newest.id
    assert missing is None
    await engine.dispose()
