"""Enabling or disabling a trigger stays inside the caller's workspace.

``enable_trigger``/``disable_trigger`` updated by primary key alone, while every
read beside them filtered by workspace. A caller who knew another tenant's
trigger id -- the MCP ``triggers_enable``/``triggers_disable`` tools take it as
a bare argument -- could switch that tenant's schedule on or off.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.testing import sqlite_compat  # noqa: F401
from agentarea_triggers.domain.enums import TriggerType
from agentarea_triggers.infrastructure.orm import TriggerORM
from agentarea_triggers.infrastructure.repository import TriggerRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OWNER_WS = "workspace-owner"
OTHER_WS = "workspace-other"


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[TriggerORM.__table__]
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def _seed(session, *, is_active: bool):
    now = datetime.utcnow()
    trigger = TriggerORM(
        id=uuid4(),
        name="nightly",
        description="",
        agent_id=uuid4(),
        trigger_type=TriggerType.CRON.value,
        is_active=is_active,
        task_parameters={},
        conditions={},
        created_at=now,
        updated_at=now,
        created_by="user-owner",
        workspace_id=OWNER_WS,
        failure_threshold=5,
        consecutive_failures=0,
        cron_expression="0 3 * * *",
        timezone="UTC",
    )
    session.add(trigger)
    await session.commit()
    return trigger.id


def _repository(session, workspace_id: str) -> TriggerRepository:
    return TriggerRepository(session, UserContext(user_id="someone", workspace_id=workspace_id))


async def _is_active(session, trigger_id) -> bool:
    session.expire_all()
    return (await session.get(TriggerORM, trigger_id)).is_active


@pytest.mark.asyncio
async def test_another_workspace_cannot_disable_the_trigger(session_factory) -> None:
    async with session_factory() as session:
        trigger_id = await _seed(session, is_active=True)

        assert await _repository(session, OTHER_WS).disable_trigger(trigger_id) is False
        assert await _is_active(session, trigger_id) is True


@pytest.mark.asyncio
async def test_another_workspace_cannot_enable_the_trigger(session_factory) -> None:
    async with session_factory() as session:
        trigger_id = await _seed(session, is_active=False)

        assert await _repository(session, OTHER_WS).enable_trigger(trigger_id) is False
        assert await _is_active(session, trigger_id) is False


@pytest.mark.asyncio
async def test_the_owning_workspace_still_toggles_it(session_factory) -> None:
    async with session_factory() as session:
        trigger_id = await _seed(session, is_active=True)
        repository = _repository(session, OWNER_WS)

        assert await repository.disable_trigger(trigger_id) is True
        assert await _is_active(session, trigger_id) is False
        assert await repository.enable_trigger(trigger_id) is True
        assert await _is_active(session, trigger_id) is True
