"""The inbox total counts the same rows the inbox page lists.

``list_by_statuses`` narrowed by ``agent_id`` while ``count_by_statuses`` could
not, so an inbox filtered to one agent showed that agent's items under the
whole workspace's total.
"""

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


async def test_the_count_narrows_by_agent_as_the_list_does():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, agent_a, agent_b = str(uuid4()), uuid4(), uuid4()
    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=ws))
        now = datetime.now(UTC)
        for agent_id, status in [
            (agent_a, "completed"),
            (agent_a, "failed"),
            (agent_a, "running"),
            (agent_b, "completed"),
        ]:
            await repo.create_task(
                Task(
                    id=uuid4(),
                    agent_id=agent_id,
                    description="d",
                    parameters={},
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )
        statuses = ["completed", "failed"]

        assert await repo.count_by_statuses(statuses) == 3
        for agent_id, expected in [(agent_a, 2), (agent_b, 1), (uuid4(), 0)]:
            listed = await repo.list_by_statuses(statuses, agent_id=agent_id)
            assert len(listed) == expected
            assert await repo.count_by_statuses(statuses, agent_id=agent_id) == expected
    await engine.dispose()
