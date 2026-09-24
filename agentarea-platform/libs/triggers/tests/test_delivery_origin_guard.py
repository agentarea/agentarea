"""Outbound delivery only uses a trigger's credentials for its own workspace's tasks.

The adapter resolves ``channel_cred:<type>:<trigger_id>`` and the secret reader
takes the workspace from that trigger, so a ``channel_origin`` naming another
workspace's trigger replied with that workspace's bot token. The consumer is
the one place every delivery passes, so it checks the pairing there.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import agentarea_common.testing.sqlite_compat  # noqa: F401
import pytest
from agentarea_common.base.models import BaseModel
from agentarea_common.broker import BrokerMessage
from agentarea_tasks.infrastructure.orm import TaskORM
from agentarea_triggers.channels.delivery_consumer import ChannelDeliveryConsumer
from agentarea_triggers.channels.origin_guard import TriggerWorkspaceGuard
from agentarea_triggers.infrastructure.orm import TriggerORM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

VICTIM = "ws-victim"
ATTACKER = "ws-attacker"


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[TriggerORM.__table__, TaskORM.__table__]
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


async def _trigger(session_factory, workspace_id: str) -> uuid.UUID:
    trigger_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            TriggerORM(
                id=trigger_id,
                name="bot",
                agent_id=uuid.uuid4(),
                trigger_type="webhook",
                workspace_id=workspace_id,
                created_by="owner",
            )
        )
        await session.commit()
    return trigger_id


async def _task(session_factory, workspace_id: str) -> uuid.UUID:
    task_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            TaskORM(
                id=task_id,
                agent_id=uuid.uuid4(),
                description="run",
                status="running",
                started_at=datetime.utcnow(),
                workspace_id=workspace_id,
                created_by="member",
            )
        )
        await session.commit()
    return task_id


class _Broker:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dlq: list[dict[str, str]] = []

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        self.dlq.append(dict(fields))
        return "dlq-1"

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append(message_id)


class _Dedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def claim(self, key: str) -> bool:
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def release(self, key: str) -> None:
        self.claimed.discard(key)


async def _deliver(session_factory, trigger_id: uuid.UUID, task_id: uuid.UUID):
    adapter = MagicMock()
    adapter.send = AsyncMock()
    broker = _Broker()
    consumer = ChannelDeliveryConsumer(
        broker=broker,  # type: ignore[arg-type]
        dedup=_Dedup(),  # type: ignore[arg-type]
        adapter_resolver=lambda _t: adapter,
        origin_guard=TriggerWorkspaceGuard(session_factory),
        stream="out",
        group="g",
        dlq_stream="out:dlq",
    )
    channel_config = {
        "type": "telegram",
        "trigger_id": str(trigger_id),
        "chat_id": "1",
        "task_id": str(task_id),
        "event_type": "task.completed",
    }
    await consumer._handle(
        BrokerMessage(
            id="1-0",
            fields={
                "channel_type": "telegram",
                "channel_config": json.dumps(channel_config),
                "message": "done",
                "dedup_key": f"{task_id}:task.completed:e1",
            },
            delivery_count=1,
        )
    )
    return adapter, broker


@pytest.mark.asyncio
async def test_a_trigger_from_another_workspace_is_not_used(session_factory):
    foreign_trigger = await _trigger(session_factory, VICTIM)
    task = await _task(session_factory, ATTACKER)

    adapter, broker = await _deliver(session_factory, foreign_trigger, task)

    adapter.send.assert_not_awaited()
    assert broker.acked == ["1-0"]
    assert len(broker.dlq) == 1


@pytest.mark.asyncio
async def test_a_trigger_from_the_tasks_workspace_is_used(session_factory):
    trigger = await _trigger(session_factory, VICTIM)
    task = await _task(session_factory, VICTIM)

    adapter, broker = await _deliver(session_factory, trigger, task)

    adapter.send.assert_awaited_once()
    assert broker.dlq == []


@pytest.mark.asyncio
async def test_an_unknown_task_is_refused(session_factory):
    trigger = await _trigger(session_factory, VICTIM)

    adapter, _broker = await _deliver(session_factory, trigger, uuid.uuid4())

    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_origin_without_a_trigger_is_not_checked(session_factory):
    guard = TriggerWorkspaceGuard(session_factory)
    assert await guard({"type": "a2a_webhook", "task_id": str(uuid.uuid4())}) is True
