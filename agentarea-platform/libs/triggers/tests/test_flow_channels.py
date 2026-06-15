"""Hermetic flow test: inbound channel message -> route -> deliver.

Covers MainFlow.CHANNELS end-to-end without a live broker, Redis, or
any network connection. All external dependencies are replaced by
in-memory stubs that implement the same Protocol interfaces used in
production.

Flow under test:
  1. ChannelEventSubscriber._handle_message parses a raw pub/sub envelope.
  2. ChannelRouter.on_task_event resolves the channel_origin, picks an
     adapter, formats the message, and submits to the delivery stream.
  3. ChannelDeliveryConsumer._handle claims the message from the stub
     broker, deduplicates via an in-memory DedupCache stub, and calls
     adapter.send.
  4. Assertion: adapter.send received exactly one call with the correct
     payload; a second submission with the same dedup_key is silently
     dropped (dedup).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.broker import BrokerMessage
from agentarea_common.testing.flows import MainFlow
from agentarea_triggers.channels import register_adapter
from agentarea_triggers.channels.delivery_consumer import (
    ChannelDeliveryConsumer,
    ChannelDeliveryEmitter,
)
from agentarea_triggers.channels.router import ChannelRouter

# ---------------------------------------------------------------------------
# In-memory stubs (no network, no Redis)
# ---------------------------------------------------------------------------


class _InMemoryBroker:
    """Minimal BrokerClient stub backed by a deque."""

    def __init__(self) -> None:
        self._queue: list[BrokerMessage] = []
        self.acked: list[str] = []
        self.dlq_submits: list[tuple[str, dict[str, str]]] = []
        self._counter = 0

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        pass

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        self._counter += 1
        msg_id = f"{self._counter}-0"
        if "fatal_reason" in fields:
            # DLQ write
            self.dlq_submits.append((stream, dict(fields)))
        else:
            self._queue.append(BrokerMessage(id=msg_id, fields=fields, delivery_count=1))
        return msg_id

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 5000,
    ) -> list[BrokerMessage]:
        await asyncio.sleep(0)  # yield so the event loop can run stop() if needed
        batch, self._queue = self._queue[:count], self._queue[count:]
        return batch

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append(message_id)

    async def autoclaim(self, *_, **__) -> list[BrokerMessage]:
        return []


class _InMemoryDedup:
    """In-memory dedup: mimics DedupCache claim/release semantics."""

    def __init__(self) -> None:
        self._claimed: set[str] = set()

    async def claim(self, key: str) -> bool:
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True

    async def release(self, key: str) -> None:
        self._claimed.discard(key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pubsub_envelope(
    event_type: str,
    task_id: str,
    event_id: str,
    channel_origin: dict[str, Any],
    result: str = "task completed",
) -> bytes:
    """Build a raw pub/sub message that ChannelEventSubscriber expects."""
    envelope = {
        "id": event_id,
        "type": f"workflow.{event_type}",
        "aggregate_id": task_id,
        "data": {
            "task_id": task_id,
            "original_data": {"result": result},
            "channel_origin": channel_origin,
        },
    }
    return json.dumps(envelope).encode()


async def _run_consumer_once(consumer: ChannelDeliveryConsumer) -> None:
    """Start consumer, let it drain the stub queue, then stop."""
    await consumer.start()
    for _ in range(20):
        await asyncio.sleep(0.01)
        # Stop as soon as the queue is drained (avoid waiting for block_ms).
        if consumer._task is not None:
            break
    await consumer.stop()


# ---------------------------------------------------------------------------
# Flow test
# ---------------------------------------------------------------------------


@pytest.mark.flow(MainFlow.CHANNELS)
@pytest.mark.asyncio
async def test_inbound_channel_message_routed_and_delivered() -> None:
    """Full CHANNELS flow: inbound pub/sub -> router -> delivery consumer -> adapter.send.

    Assert that a WorkflowCompleted event with a known channel_origin is
    formatted by the adapter and delivered exactly once via adapter.send,
    and that a second submission with the identical dedup_key is silently
    dropped.
    """
    # --- Arrange -----------------------------------------------------------

    adapter_type = f"flow_test_channel_{uuid.uuid4().hex[:6]}"
    task_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    channel_origin = {
        "type": adapter_type,
        "chat_id": "99999",
        "presentation": "concise",
    }

    # Register a mock adapter that formats and records send() calls.
    mock_adapter = MagicMock()
    mock_adapter.format = MagicMock(return_value="Task is complete!")
    mock_adapter.send = AsyncMock()
    register_adapter(adapter_type, mock_adapter)

    broker = _InMemoryBroker()
    dedup = _InMemoryDedup()
    stream = f"test:flow:channels:{uuid.uuid4().hex[:8]}"
    dlq_stream = f"{stream}:dlq"

    emitter = ChannelDeliveryEmitter(broker, stream=stream)

    router = ChannelRouter(emitter=emitter)

    consumer = ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=lambda t: mock_adapter if t == adapter_type else None,
        stream=stream,
        group="flow-test-group",
        dlq_stream=dlq_stream,
        consumer_id="c-flow",
        block_ms=10,
    )

    # --- Act (step 1-2): parse pub/sub envelope and route ------------------

    raw_envelope = _make_pubsub_envelope(
        event_type="WorkflowCompleted",
        task_id=task_id,
        event_id=event_id,
        channel_origin=channel_origin,
        result="All done",
    )
    raw_message: dict[str, Any] = {
        "type": "pmessage",
        "data": raw_envelope,
    }

    # Import subscriber here to avoid top-level redis import issues in CI
    # (the subscriber module only does 'import redis.asyncio' at call time).
    from agentarea_triggers.channels.subscriber import ChannelEventSubscriber

    subscriber = ChannelEventSubscriber(router=router, redis_url="redis://unused")
    await subscriber._handle_message(raw_message)

    # Router should have submitted one message to the broker stream.
    assert len(broker._queue) == 1, "Router did not enqueue a delivery job"

    # --- Act (step 3-4): consumer processes the delivery job ---------------

    await _run_consumer_once(consumer)

    # --- Assert: delivery happened exactly once ----------------------------

    mock_adapter.format.assert_called_once()
    format_args = mock_adapter.format.call_args
    routed_event = format_args[0][0]
    assert routed_event["event_type"] == "WorkflowCompleted"
    assert routed_event["task_id"] == task_id

    mock_adapter.send.assert_awaited_once()
    sent_config, sent_message = mock_adapter.send.await_args[0]
    assert sent_config["chat_id"] == "99999"
    assert sent_message == "Task is complete!"
    assert broker.acked, "Message was not ACKed after successful delivery"

    # --- Assert: duplicate dedup_key is dropped ----------------------------

    # Submit the same event again (same dedup_key = task_id:event_type:event_id).
    dedup_key = f"{task_id}:WorkflowCompleted:{event_id}"
    await emitter.submit(
        channel_type=adapter_type,
        channel_config=channel_origin,
        message="Task is complete!",
        dedup_key=dedup_key,
    )

    # Reset the consumer's broker queue pointer so we can reuse the same instance.
    await _run_consumer_once(consumer)

    # send must still have been called only once total — dedup blocked the repeat.
    assert mock_adapter.send.await_count == 1, (
        f"Expected 1 send call total (dedup should have dropped the duplicate), "
        f"got {mock_adapter.send.await_count}"
    )
