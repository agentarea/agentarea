"""Provenance survives the real tasks table, including the parent pointer."""

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.domain.models import Task, TaskProvenance
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")


async def test_provenance_round_trips():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws, parent = str(uuid4()), uuid4()
    async with maker() as session:
        repo = TaskRepository(session, UserContext(user_id="u", workspace_id=ws))
        now = datetime.now(UTC)
        created = await repo.create_task(
            Task(
                id=uuid4(),
                agent_id=uuid4(),
                description="d",
                parameters={},
                status="pending",
                created_at=now,
                updated_at=now,
                provenance=TaskProvenance(
                    origin_type="agent",
                    origin_id=str(parent),
                    causation_id=str(parent),
                    parent_task_id=parent,
                ),
            )
        )
        again = await repo.get_task(created.id)
        assert again is not None
        assert again.provenance.parent_task_id == parent
        assert again.provenance.origin_type == "agent"
    await engine.dispose()
