"""Tests for the EventStream broadcast read side (ADR-0018).

``RedisStreamsEventStream`` is the CQRS read side: catch-up then live tail over
a Redis stream with no consumer group. The adapter logic (cursor advance,
decode, order) is tested against a fake broker; the broker's ``tail`` cursor
arithmetic is tested against a fake redis client. Neither needs a live Redis.
"""

import asyncio
from uuid import uuid4

import pytest
from agentarea_common.broker.interface import BrokerMessage
from agentarea_common.broker.redis_streams import RedisStreamsBroker
from agentarea_common.events.adapters.redis_streams import (
    RedisStreamsEventStream,
    encode,
    topic_for,
)
from agentarea_common.events.ports import IntegrationEvent

_TYPE = "agentarea.mcp.v1.MCPServerInstanceStatusChanged"


class _FakeBroker:
    """Records tail() cursors and returns scripted batches, then idles."""

    def __init__(self, batches: list[list[BrokerMessage]]) -> None:
        self._batches = list(batches)
        self.cursors: list[str] = []

    async def tail(self, stream, last_id="$", block_ms=5000, count=100):
        self.cursors.append(last_id)
        if self._batches:
            batch = self._batches.pop(0)
            if batch:
                return batch[-1].id, batch
        return last_id, []


def _msg(msg_id: str, subject: str, data: dict) -> BrokerMessage:
    fields = encode(IntegrationEvent(type=_TYPE, source="svc", subject=subject, data=data))
    return BrokerMessage(id=msg_id, fields=fields)


@pytest.mark.asyncio
async def test_read_yields_decoded_events_in_order():
    broker = _FakeBroker(
        [[_msg("1-0", "a", {"k": 1}), _msg("2-0", "b", {"k": 2})]]
    )
    stream = RedisStreamsEventStream(broker)
    gen = stream.read(stream=_TYPE)
    try:
        e1 = await gen.__anext__()
        e2 = await gen.__anext__()
    finally:
        await gen.aclose()

    assert (e1.subject, e1.data["k"]) == ("a", 1)
    assert (e2.subject, e2.data["k"]) == ("b", 2)


@pytest.mark.asyncio
async def test_read_catch_up_starts_from_zero_then_advances_cursor():
    broker = _FakeBroker([[_msg("5-0", "a", {})], [_msg("9-0", "b", {})]])
    stream = RedisStreamsEventStream(broker)
    gen = stream.read(stream=_TYPE, from_offset="0")
    try:
        await gen.__anext__()  # 5-0
        await gen.__anext__()  # 9-0 (forces a second tail call)
    finally:
        await gen.aclose()

    # First call replays from the start; the next resumes after the last id.
    assert broker.cursors[0] == "0"
    assert broker.cursors[1] == "5-0"


@pytest.mark.asyncio
async def test_read_applies_topic_for():
    seen: dict[str, str] = {}

    class _SpyBroker:
        async def tail(self, stream, last_id="$", block_ms=5000, count=100):
            seen["stream"] = stream
            raise asyncio.CancelledError

    stream = RedisStreamsEventStream(_SpyBroker())
    gen = stream.read(stream=_TYPE, from_offset="$")
    with pytest.raises(asyncio.CancelledError):
        await gen.__anext__()

    assert seen["stream"] == topic_for(_TYPE)


class _FakeRedis:
    def __init__(self, response):
        self._response = response

    async def xread(self, streams, count, block):
        return self._response


@pytest.mark.asyncio
async def test_broker_tail_advances_cursor_to_last_id():
    fields = {"ce_id": str(uuid4()), "ce_type": _TYPE, "ce_source": "s", "data": "{}"}
    response = [["events:t", [("5-0", fields), ("7-0", fields)]]]
    broker = RedisStreamsBroker("redis://unused")
    broker._client = _FakeRedis(response)  # type: ignore[assignment]

    cursor, msgs = await broker.tail("events:t", last_id="0")

    assert cursor == "7-0"
    assert [m.id for m in msgs] == ["5-0", "7-0"]


@pytest.mark.asyncio
async def test_broker_tail_timeout_keeps_cursor():
    broker = RedisStreamsBroker("redis://unused")
    broker._client = _FakeRedis(None)  # type: ignore[assignment]

    cursor, msgs = await broker.tail("events:t", last_id="9-0")

    assert cursor == "9-0"
    assert msgs == []
