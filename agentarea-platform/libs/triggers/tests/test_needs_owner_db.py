"""A trigger stopped for a new owner comes back when it is enabled again.

The stop and the enable are column updates scoped to the workspace; only the
migrated schema shows the stamp really clears. Set STREAMS_TEST_DATABASE_URL.
"""

import os
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_triggers.domain.models import TriggerUpdate
from agentarea_triggers.infrastructure.repository import TriggerRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")


async def test_enabling_a_trigger_that_needs_a_new_owner_clears_the_stop():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ctx = UserContext(user_id="u", workspace_id=str(uuid4()))
    trigger_id = uuid4()
    async with maker() as session:
        await session.execute(
            text(
                "INSERT INTO triggers (id, workspace_id, created_by, name, description, agent_id, "
                "trigger_type, is_active, task_parameters, conditions, failure_threshold, "
                "consecutive_failures, validation_rules, created_at, updated_at) VALUES (:id, :ws, "
                "'u', 't', '', :agent, 'stream', true, '{}', '{}', 5, 0, '{}', now(), now())"
            ),
            {"id": trigger_id, "ws": ctx.workspace_id, "agent": uuid4()},
        )
        repository = TriggerRepository(session, ctx)

        assert await repository.mark_needs_new_owner(trigger_id)
        stopped = await repository.get_trigger(trigger_id)
        assert stopped is not None
        assert (stopped.is_active, stopped.needs_new_owner_at is not None) == (False, True)

        assert await repository.enable_trigger(trigger_id)
        session.expire_all()
        enabled = await repository.get_trigger(trigger_id)
        assert enabled is not None
        assert (enabled.is_active, enabled.needs_new_owner_at) == (True, None)

        assert await repository.mark_needs_new_owner(trigger_id)
        await repository.update_by_id(trigger_id, TriggerUpdate.model_validate({"is_active": True}))
        session.expire_all()
        patched = await repository.get_trigger(trigger_id)
        assert patched is not None
        assert (patched.is_active, patched.needs_new_owner_at) == (True, None)

        other = TriggerRepository(session, UserContext(user_id="u", workspace_id=str(uuid4())))
        assert not await other.mark_needs_new_owner(trigger_id)
        await session.rollback()
    await engine.dispose()
