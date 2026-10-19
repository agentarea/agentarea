"""An entry a worker could not settle stays pending until a worker that can takes it.

During a rolling deploy an older worker can read a delivery whose channel it
has no adapter for (``task_webhook``, say). It must leave the entry pending,
and the autoclaimer of a worker that has the adapter must reclaim and deliver
it -- not merely move it to another consumer's pending list.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from agentarea_common.broker import BrokerMessage
from agentarea_common.events.adapters.redis_streams import encode
from agentarea_common.events.task_stream import task_event
from agentarea_triggers.channels.autoclaimer import StreamAutoclaimer
from agentarea_triggers.channels.task_delivery import DELIVERY_TARGET_FIELD, TaskEventDelivery

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

    async def submit(self, stream: str, fields: dict[str, str], *, retention) -> str:
        self.dead_letters.append(dict(fields))
        return "dlq-1"


class _Dedup:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    async def contains(self, key: str) -> bool:
        return key in self.claimed

    async def claim(self, key: str, *, hold_seconds: int | None = None) -> bool:
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True

    async def keep(self, key: str) -> None:
        self.claimed.add(key)

    async def release(self, key: str) -> None:
        self.claimed.discard(key)


async def _no_catalog_reply(_slug: str):
    return None


TASK_ID = uuid4()


async def _task_with_a_webhook(_task_id, _workspace_id):
    return SimpleNamespace(
        parameters={}, metadata={"task_webhook": {"url": "https://h/x"}}, owner="u"
    )


def _delivery_consumer(broker, dedup, adapters: dict) -> TaskEventDelivery:
    return TaskEventDelivery(
        broker,
        dedup,
        adapters.get,
        load_task=_task_with_a_webhook,
        reply_for=_no_catalog_reply,
        consumer_id="c",
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
    event = task_event(
        task_id=str(TASK_ID),
        workspace_id="ws",
        event_type="task.completed",
        event_id=str(uuid4()),
        timestamp=datetime.now(UTC),
        data={"final_response": "done"},
        seq=3,
    )
    return broker.add(encode(event))


def _webhook_adapter(**send) -> MagicMock:
    adapter = MagicMock()
    adapter.format = MagicMock(return_value='{"status": "completed"}')
    adapter.send = AsyncMock(**send)
    return adapter


async def test_a_worker_without_the_adapter_leaves_the_delivery_for_one_that_has_it():
    broker = _PendingListBroker()
    dedup = _Dedup()
    message_id = _task_webhook_delivery(broker)
    old_worker = _delivery_consumer(broker, dedup, adapters={})
    adapter = _webhook_adapter()
    new_worker = _delivery_consumer(broker, dedup, adapters={"task_webhook": adapter})

    for message in await broker.consume(STREAM, GROUP, "old"):
        await old_worker.handle(message)

    assert message_id in broker.pending
    assert broker.dead_letters == []

    broker.now_ms += IDLE_MS
    await _autoclaimer(broker, new_worker, "new-autoclaimer").reclaim()

    config, body = adapter.send.await_args.args
    assert (config["task_id"], config["url"], body) == (
        str(TASK_ID),
        "https://h/x",
        '{"status": "completed"}',
    )
    adapter.send.assert_awaited_once()
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


async def test_a_dead_lettered_delivery_delivers_when_replayed():
    from agentarea_triggers.channels.exceptions import FatalError

    broker = _PendingListBroker()
    dedup = _Dedup()
    _task_webhook_delivery(broker)
    adapter = _webhook_adapter(side_effect=[FatalError("endpoint gone"), None])
    worker = _delivery_consumer(broker, dedup, adapters={"task_webhook": adapter})
    for message in await broker.consume(STREAM, GROUP, "w"):
        await worker.handle(message)
    assert len(broker.dead_letters) == 1

    replayed = {k: v for k, v in broker.dead_letters[0].items() if k != "fatal_reason"}
    assert replayed[DELIVERY_TARGET_FIELD] == "task_webhook"
    broker.add(replayed)
    for message in await broker.consume(STREAM, GROUP, "w"):
        await worker.handle(message)

    assert adapter.send.await_count == 2
    assert broker.pending == {}
    assert len(broker.dead_letters) == 1
