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


async def test_a_task_no_event_started_begins_its_own_chain_and_its_spend_carries_it():
    from decimal import Decimal

    from agentarea_tasks.domain.costs import CostCategory, CostEntry, CostSource, CostSubjectType
    from agentarea_tasks.infrastructure.cost_repository import CostEntryRepository
    from sqlalchemy import text

    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ws = str(uuid4())
    async with maker() as session:
        context = UserContext(user_id="u", workspace_id=ws)
        now = datetime.now(UTC)
        task = await TaskRepository(session, context).create_task(
            Task(
                id=uuid4(),
                agent_id=uuid4(),
                description="from the API",
                parameters={},
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
        await CostEntryRepository(session, context).record(
            [
                CostEntry(
                    workspace_id=ws,
                    created_by="u",
                    event_id=uuid4(),
                    category=CostCategory.MODEL,
                    task_id=task.id,
                    agent_id=task.agent_id,
                    subject_type=CostSubjectType.MODEL_INSTANCE,
                    subject_id=None,
                    subject_name="m",
                    call_ref=None,
                    amount=Decimal("0.01"),
                    currency="USD",
                    source=CostSource.TOKEN_PRICING,
                    occurred_at=now,
                )
            ]
        )
        stored = await session.scalar(
            text("SELECT correlation_id FROM cost_entries WHERE task_id = :t"), {"t": task.id}
        )
        await session.rollback()
    assert task.provenance.correlation_id == str(task.id)
    assert stored == str(task.id)
    await engine.dispose()
