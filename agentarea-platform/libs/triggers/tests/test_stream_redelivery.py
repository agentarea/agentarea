"""An entry a worker could not settle stays pending until a worker that can takes it.

During a rolling deploy an older worker can read a delivery whose channel it
has no adapter for (``task_webhook``, say). It must leave the entry pending,
and the autoclaimer of a worker that has the adapter must reclaim and deliver
it -- not merely move it to another consumer's pending list.
"""

import json
from unittest.mock import AsyncMock, MagicMock

from agentarea_common.broker import BrokerMessage
from agentarea_triggers.channels.autoclaimer import StreamAutoclaimer
from agentarea_triggers.channels.delivery_consumer import ChannelDeliveryConsumer
from agentarea_triggers.channels.inbound_subscriber import InboundMessageStreamConsumer

STREAM = "out"
GROUP = "workers"
IDLE_MS = 60_000


class _PendingListBroker:
    """One stream and one consumer group, with Redis' pending-entries semantics."""

    def __init__(self) -> None:
        self.now_ms = 0
        self._entries: list[tuple[str, dict[str, str]]] = []
        self._next_new = 0
        self.pending: dict[str, dict] = {}
        self.dead_letters: list[dict[str, str]] = []

    def add(self, fields: dict[str, str]) -> str:
        message_id = f"{len(self._entries) + 1}-0"
        self._entries.append((message_id, fields))
        return message_id

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        pass

    async def consume(self, stream, group, consumer, count=10, block_ms=0):
        batch = self._entries[self._next_new : self._next_new + count]
        self._next_new += len(batch)
        for message_id, _ in batch:
            self.pending[message_id] = {"consumer": consumer, "at": self.now_ms, "count": 1}
        return [BrokerMessage(id=mid, fields=fields, delivery_count=1) for mid, fields in batch]

    async def autoclaim(self, stream, group, consumer, min_idle_ms, start="0-0", count=100):
        claimed = []
        for message_id, fields in self._entries:
            entry = self.pending.get(message_id)
            if entry is None or self.now_ms - entry["at"] < min_idle_ms:
                continue
            entry.update(consumer=consumer, at=self.now_ms, count=entry["count"] + 1)
            claimed.append(BrokerMessage(id=message_id, fields=fields, delivery_count=entry["count"]))
        return claimed

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.pending.pop(message_id, None)

    async def submit(self, stream: str, fields: dict[str, str]) -> str:
        self.dead_letters.append(dict(fields))
        return "dlq-1"


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


async def _origin_allowed(_config: dict) -> bool:
    return True


def _delivery_consumer(broker, dedup, adapters: dict) -> ChannelDeliveryConsumer:
    return ChannelDeliveryConsumer(
        broker=broker,
        dedup=dedup,
        adapter_resolver=adapters.get,
        origin_guard=_origin_allowed,
        stream=STREAM,
        group=GROUP,
        dlq_stream="out:dlq",
    )


def _autoclaimer(broker, consumer, consumer_id: str) -> StreamAutoclaimer:
    return StreamAutoclaimer(
        broker,
        stream=STREAM,
        group=GROUP,
        consumer_id=consumer_id,
        min_idle_ms=IDLE_MS,
        handle=consumer.handle,
    )


def _task_webhook_delivery(broker: _PendingListBroker) -> str:
    return broker.add(
        {
            "channel_type": "task_webhook",
            "channel_config": json.dumps({"task_id": "t-1"}),
            "message": '{"status": "completed"}',
            "dedup_key": "t-1:task.completed",
        }
    )


async def test_a_worker_without_the_adapter_leaves_the_delivery_for_one_that_has_it():
    broker = _PendingListBroker()
    dedup = _Dedup()
    message_id = _task_webhook_delivery(broker)
    old_worker = _delivery_consumer(broker, dedup, adapters={})
    adapter = MagicMock()
    adapter.send = AsyncMock()
    new_worker = _delivery_consumer(broker, dedup, adapters={"task_webhook": adapter})

    for message in await broker.consume(STREAM, GROUP, "old"):
        await old_worker.handle(message)

    assert message_id in broker.pending
    assert broker.dead_letters == []

    broker.now_ms += IDLE_MS
    await _autoclaimer(broker, new_worker, "new-autoclaimer").reclaim()

    adapter.send.assert_awaited_once_with({"task_id": "t-1"}, '{"status": "completed"}')
    assert broker.pending == {}
    assert broker.dead_letters == []


async def test_a_reclaiming_worker_without_the_adapter_keeps_the_delivery_pending():
    broker = _PendingListBroker()
    message_id = _task_webhook_delivery(broker)
    worker = _delivery_consumer(broker, _Dedup(), adapters={})
    autoclaimer = _autoclaimer(broker, worker, "autoclaimer")
    for message in await broker.consume(STREAM, GROUP, "c1"):
        await worker.handle(message)

    # Not yet idle: nothing is taken, so an unhandled entry is not spun on.
    assert await autoclaimer.reclaim() == 0
    broker.now_ms += IDLE_MS
    assert await autoclaimer.reclaim() == 1

    assert broker.pending[message_id]["count"] == 2
    assert broker.dead_letters == []


class _InboundConsumer(InboundMessageStreamConsumer):
    def __init__(self, broker, dedup):
        super().__init__(
            broker,
            dedup,
            event_broker=AsyncMock(),
            secret_manager_factory=MagicMock(),
            stream=STREAM,
            group=GROUP,
            dlq_stream="in:dlq",
        )
        self.failures_left = 1
        self.executed: list[str] = []

    async def _execute_trigger(self, trigger_id: str, trigger_data: dict) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("database restarting")
        self.executed.append(trigger_id)


async def test_an_inbound_event_whose_firing_failed_is_fired_again_once_reclaimed():
    broker = _PendingListBroker()
    broker.add({"trigger_id": "trg-1", "event": "{}", "channel_origin": "{}", "dedup_key": "e-1"})
    consumer = _InboundConsumer(broker, _Dedup())

    for message in await broker.consume(STREAM, GROUP, "c1"):
        await consumer.handle(message)
    assert consumer.executed == []

    broker.now_ms += IDLE_MS
    await _autoclaimer(broker, consumer, "inbound-autoclaimer").reclaim()

    assert consumer.executed == ["trg-1"]
    assert broker.pending == {}
