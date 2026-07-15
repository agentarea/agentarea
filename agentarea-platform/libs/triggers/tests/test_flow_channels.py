"""Hermetic flow test: workflow event -> emit -> deliver.

Covers MainFlow.CHANNELS end-to-end without a live broker, Redis, or
any network connection. All external dependencies are replaced by
in-memory stubs that implement the same Protocol interfaces used in
production.

Flow under test (the live delivery path):
  1. `emit_channel_delivery` runs the routing decision inside the
     Temporal activity: visibility filter, channel resolution, adapter
     format, dedup_key construction, and submit to the outbound stream.
  2. ChannelDeliveryConsumer._handle claims the message from the stub
     broker, deduplicates via an in-memory DedupCache stub, and calls
     adapter.send.
  3. Assertion: adapter.send received exactly one call with the correct
     payload; a second emit for the same event (same dedup_key) is
     silently dropped (dedup).
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.broker import BrokerMessage
from agentarea_common.testing.flows import MainFlow
from agentarea_triggers.channels import register_adapter
from agentarea_triggers.channels.activity_emit import emit_channel_delivery
from agentarea_triggers.channels.delivery_consumer import ChannelDeliveryConsumer

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
async def test_workflow_event_emitted_and_delivered() -> None:
    """Full CHANNELS flow: emit_channel_delivery -> delivery consumer -> adapter.send.

    Assert that a WorkflowCompleted event with a known channel_origin is
    formatted by the adapter and delivered exactly once via adapter.send,
    and that a second emit of the same event (identical dedup_key) is
    silently dropped.
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

    event = {
        "event_type": "WorkflowCompleted",
        "task_id": task_id,
        "event_id": event_id,
        "data": {"result": "All done"},
    }

    # --- Act (step 1): emit runs the routing decision + enqueues -----------

    submitted = await emit_channel_delivery(
        event=event,
        channel_origin=channel_origin,
        broker=broker,
        stream=stream,
    )
    assert submitted is True, "emit_channel_delivery did not enqueue a delivery job"
    assert len(broker._queue) == 1, "emit did not enqueue exactly one delivery job"

    # --- Act (step 2): consumer processes the delivery job -----------------

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

    # --- Assert: re-emitting the same event is dropped by dedup ------------

    # Same (task_id, event_type, event_id) => same dedup_key.
    await emit_channel_delivery(
        event=event,
        channel_origin=channel_origin,
        broker=broker,
        stream=stream,
    )
    await _run_consumer_once(consumer)

    # send must still have been called only once total — dedup blocked the repeat.
    assert mock_adapter.send.await_count == 1, (
        f"Expected 1 send call total (dedup should have dropped the duplicate), "
        f"got {mock_adapter.send.await_count}"
    )
