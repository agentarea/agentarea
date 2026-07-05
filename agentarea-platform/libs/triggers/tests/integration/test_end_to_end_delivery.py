"""End-to-end smoke: workflow event → emit_channel_delivery → outbound
stream → delivery consumer → adapter.

Simulates "as if a Telegram message came in and a workflow replied" without
needing a real Telegram bot or a running workflow — proves the full
production delivery pipeline (the in-activity emitter + durable stream +
consumer) executes and lands the message at the adapter.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from agentarea_common.broker import DedupCache, RedisStreamsBroker
from agentarea_triggers.channels import register_adapter
from agentarea_triggers.channels.activity_emit import emit_channel_delivery
from agentarea_triggers.channels.delivery_consumer import ChannelDeliveryConsumer

pytestmark = pytest.mark.asyncio

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class CapturingTelegramAdapter:
    """Stand-in for the Telegram HTTP adapter — records would-be sends."""

    def __init__(self) -> None:
        self.sent: list[tuple[dict, str]] = []

    def format(self, event, presentation: str) -> str:
        data = event.get("data", {})
        return str(data.get("result") or data.get("final_response") or "")

    async def send(self, channel_config, message: str) -> None:
        self.sent.append((channel_config, message))


def _make_event(event_id: str, task_id: str, result: str) -> dict:
    """Workflow event as seen by emit_channel_delivery inside the activity."""
    return {
        "event_type": "WorkflowCompleted",
        "task_id": task_id,
        "event_id": event_id,
        "data": {"result": result},
    }


def _origin() -> dict:
    return {
        "type": "telegram",
        "chat_id": "12345",
        "presentation": "concise",
        "trigger_id": str(uuid.uuid4()),
    }


@pytest_asyncio.fixture()
async def pipeline():
    """Spin up the production delivery pipeline rooted at unique streams."""
    test_id = uuid.uuid4().hex[:8]
    stream = f"e2e:outbound:{test_id}"
    group = "delivery"
    dlq = f"e2e:outbound:dlq:{test_id}"

    broker = RedisStreamsBroker(REDIS_URL)
    dedup = DedupCache(REDIS_URL, prefix=f"e2e-dedup-{test_id}", ttl_seconds=60)
    try:
        await broker.ensure_group(stream, group, start="0")
    except Exception as exc:
        pytest.skip(f"Redis not reachable: {exc}")

    adapter = CapturingTelegramAdapter()
    register_adapter("telegram", adapter)

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

    await consumer.start()

    yield adapter, broker, stream

    await consumer.stop()
    await broker.aclose()
    await dedup.aclose()


async def test_workflow_completed_event_lands_at_telegram_adapter(pipeline):
    adapter, broker, stream = pipeline

    task_id = str(uuid.uuid4())
    submitted = await emit_channel_delivery(
        event=_make_event(str(uuid.uuid4()), task_id, "Hello from agent"),
        channel_origin=_origin(),
        broker=broker,
        stream=stream,
    )
    assert submitted is True

    for _ in range(60):
        if adapter.sent:
            break
        await asyncio.sleep(0.05)

    assert adapter.sent, "adapter.send never invoked — pipeline broken"
    cfg, msg = adapter.sent[0]
    assert cfg["chat_id"] == "12345"
    assert msg == "Hello from agent"


async def test_duplicate_emit_results_in_single_delivery(pipeline):
    adapter, broker, stream = pipeline

    task_id = str(uuid.uuid4())
    event = _make_event(str(uuid.uuid4()), task_id, "dedup test")
    origin = _origin()

    # Same event emitted twice → identical dedup_key → single delivery.
    await emit_channel_delivery(event=event, channel_origin=origin, broker=broker, stream=stream)
    await emit_channel_delivery(event=event, channel_origin=origin, broker=broker, stream=stream)

    await asyncio.sleep(2.0)
    assert len(adapter.sent) == 1


async def test_two_distinct_events_same_task_both_deliver(pipeline):
    """Two distinct events on the same task each get their own dedup slot
    (dedup_key = task_id:event_type:event_id), so both are delivered.
    """
    adapter, broker, stream = pipeline

    task_id = str(uuid.uuid4())

    await emit_channel_delivery(
        event=_make_event(str(uuid.uuid4()), task_id, "first"),
        channel_origin=_origin(),
        broker=broker,
        stream=stream,
    )
    await emit_channel_delivery(
        event=_make_event(str(uuid.uuid4()), task_id, "second"),
        channel_origin=_origin(),
        broker=broker,
        stream=stream,
    )

    for _ in range(60):
        if len(adapter.sent) >= 2:
            break
        await asyncio.sleep(0.05)

    assert len(adapter.sent) == 2
    bodies = sorted(msg for _cfg, msg in adapter.sent)
    assert bodies == ["first", "second"]
