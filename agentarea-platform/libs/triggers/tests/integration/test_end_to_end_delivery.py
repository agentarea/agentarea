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
    """Stand-in for the Telegram HTTP adapter — records would-be sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[dict, str]] = []

    def format(self, event, presentation: str) -> str:
        data = event.get("data", {})
        return str(data.get("result") or data.get("final_response") or "")

    async def send(self, channel_config, message: str) -> None:
        self.sent.append((channel_config, message))


@pytest_asyncio.fixture()
async def pipeline():
    """Spin up the entire production pipeline rooted at unique streams."""
    test_id = uuid.uuid4().hex[:8]
    stream = f"e2e:outbound:{test_id}"
    group = "delivery"
    dlq = f"e2e:outbound:dlq:{test_id}"

    redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    broker = RedisStreamsBroker(REDIS_URL)
    dedup = DedupCache(REDIS_URL, prefix=f"e2e-dedup-{test_id}", ttl_seconds=60)
    try:
        await broker.ensure_group(stream, group, start="0")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")

    adapter = CapturingTelegramAdapter()
    register_adapter("telegram", adapter)

    emitter = ChannelDeliveryEmitter(broker, stream=stream)
    router = ChannelRouter(emitter=emitter, task_lookup=None)
    subscriber = ChannelEventSubscriber(router=router, redis_url=REDIS_URL)
    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda t: adapter if t == "telegram" else None,
        stream=stream,
        group=group,
        dlq_stream=dlq,
        consumer_id="e2e",
        block_ms=200,
    )

    await subscriber.start()
    await consumer.start()
    # Pub/sub drops messages with no subscribers — wait for psubscribe to land.
    await asyncio.sleep(0.3)

    yield adapter, redis_client

    await subscriber.stop()
    await consumer.stop()
    await broker.aclose()
    await dedup.aclose()
    await redis_client.aclose()


async def test_workflow_completed_event_lands_at_telegram_adapter(pipeline):
    adapter, redis_client = pipeline

    task_id = str(uuid.uuid4())
    # Realistic CloudEvents envelope as published by RedisEventBroker:
    # event_id lives at root ("id"), NOT inside data. The subscriber +
    # router must pull it from the root for dedup to work in production.
    envelope = {
        "specversion": "1.0",
        "type": "workflow.WorkflowCompleted",
        "source": "agentarea-api",
        "id": str(uuid.uuid4()),
        "aggregate_id": task_id,
        "data": {
            "task_id": task_id,
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

    for _ in range(60):
        if adapter.sent:
            break
        await asyncio.sleep(0.05)

    assert adapter.sent, "adapter.send never invoked — pipeline broken"
    cfg, msg = adapter.sent[0]
    assert cfg["chat_id"] == "12345"
    assert msg == "Hello from agent"


async def test_duplicate_publish_results_in_single_delivery(pipeline):
    adapter, redis_client = pipeline

    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    envelope = {
        "specversion": "1.0",
        "type": "workflow.WorkflowCompleted",
        "source": "agentarea-api",
        "id": event_id,
        "aggregate_id": task_id,
        "data": {
            "task_id": task_id,
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


async def test_two_distinct_events_same_task_both_deliver(pipeline):
    """Regression for the bug where event_id was looked up inside `data`
    instead of the envelope root: two distinct events on the same task
    used to dedup-collapse to one delivery. With event_id at root, each
    event has its own dedup slot and both go through.
    """
    adapter, redis_client = pipeline

    task_id = str(uuid.uuid4())

    def make_envelope(event_id: str, body: str) -> dict:
        return {
            "specversion": "1.0",
            "type": "workflow.WorkflowCompleted",
            "source": "agentarea-api",
            "id": event_id,
            "aggregate_id": task_id,
            "data": {
                "task_id": task_id,
                "original_data": {"result": body},
                "channel_origin": {
                    "type": "telegram",
                    "chat_id": "555",
                    "presentation": "concise",
                    "trigger_id": str(uuid.uuid4()),
                },
            },
        }

    await redis_client.publish(WORKFLOW_CHANNEL, json.dumps(make_envelope(str(uuid.uuid4()), "first")))
    await redis_client.publish(WORKFLOW_CHANNEL, json.dumps(make_envelope(str(uuid.uuid4()), "second")))

    for _ in range(60):
        if len(adapter.sent) >= 2:
            break
        await asyncio.sleep(0.05)

    assert len(adapter.sent) == 2
    bodies = sorted(msg for _cfg, msg in adapter.sent)
    assert bodies == ["first", "second"]
