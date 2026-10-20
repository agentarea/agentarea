"""The router's cache follows subscription changes on ``domain.events`` (ADR-0040 §5)."""

import asyncio
from uuid import uuid4

from agentarea_common.broker import BrokerMessage
from agentarea_common.broker.topics import domain_events_topic
from agentarea_common.events.adapters.redis_streams import encode
from agentarea_common.events.ports import IntegrationEvent
from agentarea_streams.domain.events import SUBSCRIPTIONS_CHANGED
from agentarea_streams.infrastructure.subscription_changes import SubscriptionChangeListener

TOPIC = domain_events_topic(SUBSCRIPTIONS_CHANGED)


class _Broker:
    def __init__(self, batches):
        self.batches = list(batches)
        self.tailed: list[tuple[str, str]] = []

    async def last_id(self, stream: str) -> str:
        assert stream == TOPIC
        return "5-0"

    async def tail(self, stream, last_id="$", block_ms=5000, count=100):
        self.tailed.append((stream, last_id))
        if not self.batches:
            await asyncio.sleep(3600)
        batch = self.batches.pop(0)
        if isinstance(batch, Exception):
            raise batch
        return (batch[-1].id if batch else last_id), batch


def _notice(message_id: str, stream_id) -> BrokerMessage:
    event = IntegrationEvent(
        type=SUBSCRIPTIONS_CHANGED,
        source="outbox",
        data={"stream_id": str(stream_id) if stream_id else None},
    )
    return BrokerMessage(id=message_id, fields=encode(event), stream=TOPIC)


async def _run(broker, changes: list, until: int) -> None:
    listener = SubscriptionChangeListener(broker, retry_seconds=0)
    await listener.start(changes.append)
    for _ in range(200):
        if len(changes) >= until:
            break
        await asyncio.sleep(0.01)
    await listener.stop()


async def test_it_drops_everything_then_follows_each_change_from_now_on():
    one, two = uuid4(), uuid4()
    broker = _Broker([[_notice("6-0", one), _notice("7-0", two)]])
    changes: list = []
    await _run(broker, changes, until=3)
    assert changes == [None, one, two]
    assert broker.tailed[0] == (TOPIC, "5-0")
    assert broker.tailed[1] == (TOPIC, "7-0")


async def test_a_notice_naming_no_stream_drops_everything():
    broker = _Broker([[_notice("6-0", None)]])
    changes: list = []
    await _run(broker, changes, until=2)
    assert changes == [None, None]


async def test_after_a_broker_failure_it_drops_everything_and_resumes_where_it_was():
    one = uuid4()
    broker = _Broker([ConnectionError("redis went away"), [_notice("6-0", one)]])
    changes: list = []
    await _run(broker, changes, until=3)
    assert changes == [None, None, one]
    assert broker.tailed[1] == (TOPIC, "5-0")
