"""End-to-end smoke: synthetic workflow event → pub/sub bridge → router →
outbound stream → delivery consumer → adapter.

Simulates "as if a Telegram message came in and a workflow replied" without
needing a real Telegram bot or a running workflow — proves the full
production pipeline path executes and lands the message at the adapter.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as redis

from agentarea_common.broker import DedupCache, RedisStreamsBroker
from agentarea_triggers.channels import register_adapter
from agentarea_triggers.channels.delivery_consumer import (
    ChannelDeliveryConsumer,
    ChannelDeliveryEmitter,
)
from agentarea_triggers.channels.router import ChannelRouter
from agentarea_triggers.channels.subscriber import ChannelEventSubscriber

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
WORKFLOW_CHANNEL = "agentarea.events.workflow.WorkflowCompleted"


class CapturingTelegramAdapter:
    """Stand-in for the Telegram HTTP adapter: records what it would send
    instead of actually hitting api.telegram.org."""

    def __init__(self) -> None:
        self.sent: list[tuple[dict, str]] = []

    def format(self, event, presentation: str) -> str:
        data = event.get("data", {})
        return str(data.get("result") or data.get("final_response") or "")

    async def send(self, channel_config, message: str) -> None:
        self.sent.append((channel_config, message))


@pytest_asyncio.fixture()
async def pipeline():
    """Spin up the entire production pipeline rooted at a unique stream so
    parallel runs don't collide.
    """
    test_id = uuid.uuid4().hex[:8]
    stream = f"e2e:outbound:{test_id}"
    group = "delivery"
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    # Patch the module-level stream constants so emitter + consumer agree on
    # the per-test stream name.
    import agentarea_triggers.channels.delivery_consumer as dc
    saved_stream, saved_group = dc.OUTBOUND_STREAM, dc.OUTBOUND_GROUP
    dc.OUTBOUND_STREAM = stream
    dc.OUTBOUND_GROUP = group

    broker = RedisStreamsBroker(REDIS_URL)
    dedup = DedupCache(REDIS_URL, prefix=f"e2e-dedup-{test_id}", ttl_seconds=60)
    try:
        await broker.ensure_group(stream, group, start="0")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")

    adapter = CapturingTelegramAdapter()
    register_adapter("telegram", adapter)

    emitter = ChannelDeliveryEmitter(broker)
    router = ChannelRouter(emitter=emitter, task_lookup=None)
    subscriber = ChannelEventSubscriber(router=router, redis_url=REDIS_URL)
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda t: adapter if t == "telegram" else None,
        consumer_id="e2e",
        block_ms=200,
    )

    await subscriber.start()
    await consumer.start()
    # Give the pub/sub subscription a beat to actually subscribe before we
    # start publishing — Redis pub/sub drops messages with no subscribers.
    await asyncio.sleep(0.3)

    yield adapter, redis_client

    await subscriber.stop()
    await consumer.stop()
    await broker.aclose()
    await dedup.aclose()
    await redis_client.aclose()
    dc.OUTBOUND_STREAM, dc.OUTBOUND_GROUP = saved_stream, saved_group


async def test_workflow_completed_event_lands_at_telegram_adapter(pipeline):
    """Drive the full pipeline with a single synthetic completion event."""
    adapter, redis_client = pipeline

    task_id = str(uuid.uuid4())
    envelope = {
        "type": "workflow.WorkflowCompleted",
        "aggregate_id": task_id,
        "data": {
            "task_id": task_id,
            "event_id": str(uuid.uuid4()),
            "original_data": {
                "result": "Hello from agent",
            },
            "channel_origin": {
                "type": "telegram",
                "chat_id": "12345",
                "presentation": "concise",
                "trigger_id": str(uuid.uuid4()),
            },
        },
    }

    await redis_client.publish(WORKFLOW_CHANNEL, json.dumps(envelope))

    # Bridge subscriber dispatches → router formats + submits to stream →
    # consumer reads stream + calls adapter. Wait up to ~3s for all hops.
    for _ in range(60):
        if adapter.sent:
            break
        await asyncio.sleep(0.05)

    assert adapter.sent, "adapter.send never invoked — pipeline broken"
    cfg, msg = adapter.sent[0]
    assert cfg["chat_id"] == "12345"
    assert msg == "Hello from agent"


async def test_duplicate_publish_results_in_single_delivery(pipeline):
    """Same event_id published twice → adapter.send called exactly once
    (dedup at consumer level)."""
    adapter, redis_client = pipeline

    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    envelope = {
        "type": "workflow.WorkflowCompleted",
        "aggregate_id": task_id,
        "data": {
            "task_id": task_id,
            "event_id": event_id,
            "original_data": {"result": "dedup test"},
            "channel_origin": {
                "type": "telegram",
                "chat_id": "999",
                "presentation": "concise",
                "trigger_id": str(uuid.uuid4()),
            },
        },
    }

    await redis_client.publish(WORKFLOW_CHANNEL, json.dumps(envelope))
    await redis_client.publish(WORKFLOW_CHANNEL, json.dumps(envelope))

    await asyncio.sleep(2.0)
    assert len(adapter.sent) == 1
