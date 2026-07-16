"""Behavior tests for RedisEventBroker (raw-redis publish path).

Uses a minimal in-memory fake redis client so no server is needed. These lock
that every channel publishes via the single raw-redis path with the exact
SharedEventFormat payload (the Python<->Go contract).
"""

from __future__ import annotations

import json

import pytest
from agentarea_common.events.base_events import DomainEvent
from agentarea_common.events.redis_event_broker import RedisEventBroker


class FakeRedis:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []
        self.closed = False

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_publish_mcp_event_uses_raw_redis_and_shared_format():
    fake = FakeRedis()
    broker = RedisEventBroker(fake)

    event = DomainEvent(
        event_type="com.agentarea.mcp.instance.created",
        aggregate_id="inst-1",
        aggregate_type="mcp_instance",
        original_event_type="com.agentarea.mcp.instance.created",
        original_data={"instance_id": "inst-1"},
        instance_id="inst-1",
    )
    await broker.publish(event)

    assert len(fake.published) == 1
    channel, message = fake.published[0]
    assert channel == "agentarea.events.mcp.instance.created"

    decoded = json.loads(message)
    assert decoded["specversion"] == "1.0"
    assert decoded["type"] == "com.agentarea.mcp.instance.created"
    assert decoded["source"] == "agentarea-api"
    assert decoded["datacontenttype"] == "application/json"
    assert decoded["data"]["instance_id"] == "inst-1"


@pytest.mark.asyncio
async def test_workflow_event_also_publishes_via_raw_redis():
    fake = FakeRedis()
    broker = RedisEventBroker(fake)

    event = DomainEvent(
        event_type="workflow.TaskStarted",
        aggregate_id="task-1",
        aggregate_type="task",
        original_event_type="TaskStarted",
        original_data={"task_id": "task-1"},
        task_id="task-1",
    )
    await broker.publish(event)

    assert len(fake.published) == 1
    channel, _ = fake.published[0]
    assert channel == "agentarea.events.workflow.TaskStarted"


@pytest.mark.asyncio
async def test_broker_does_not_close_client_it_does_not_own():
    fake = FakeRedis()
    broker = RedisEventBroker(fake)
    await broker.close()
    # An injected client is owned by the caller; broker must not close it.
    assert fake.closed is False


def test_url_construction_defers_client_creation():
    broker = RedisEventBroker("redis://localhost:6379")
    assert broker.raw_redis is None
