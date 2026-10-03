import os
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_common.auth.context import UserContext
from agentarea_common.base.tenant_scope import workspace_scope
from agentarea_tasks.infrastructure.orm import TaskORM
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

EVALS_DB = os.getenv("EVALS_TEST_DATABASE_URL", "")
needs_db = pytest.mark.skipif(not EVALS_DB, reason="EVALS_TEST_DATABASE_URL not set")


@pytest.fixture
def context():
    return UserContext(user_id="user-a", workspace_id=f"ws-{uuid4()}")


@pytest.fixture
async def session(context):
    engine = create_async_engine(EVALS_DB)
    async with engine.connect() as conn:
        transaction = await conn.begin()
        async with AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as s:
            with workspace_scope(context.workspace_id):
                yield s
        await transaction.rollback()
    await engine.dispose()


async def make_agent(session, context, *, instruction="Help.") -> Agent:
    agent = Agent(
        name="Support",
        slug=f"support-{uuid4().hex[:8]}",
        instruction=instruction,
        model_id="m-1",
        tools=[],
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(agent)
    await session.commit()
    return agent


async def make_task(
    session, context, agent, *, status, revision_id=None, experiment_id=None, metadata=None
) -> TaskORM:
    task = TaskORM(
        agent_id=agent.id,
        description="do it",
        parameters={},
        status=status,
        agent_revision_id=revision_id,
        experiment_id=experiment_id,
        task_metadata=metadata or {},
        workspace_id=context.workspace_id,
        created_by=context.user_id,
    )
    session.add(task)
    await session.commit()
    return task


async def make_tasks(
    session, context, agent, *, count, status, revision_id, experiment_id=None, metadata=None
) -> None:
    session.add_all(
        TaskORM(
            agent_id=agent.id,
            description="do it",
            parameters={},
            status=status,
            agent_revision_id=revision_id,
            experiment_id=experiment_id,
            task_metadata=metadata or {},
            workspace_id=context.workspace_id,
            created_by=context.user_id,
        )
        for _ in range(count)
    )
    await session.commit()
