"""Notices to the events pages open on a workspace: one pub/sub channel per workspace."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from agentarea_streams.domain import StreamEvent
from agentarea_streams.infrastructure.live import (
    BrokerEventNotices,
    EventNotice,
    EventNoticesHub,
    NoticeKind,
)


class _Broker:
    """notify() reaches every live connection subscribed to the channel."""

    def __init__(self) -> None:
        self.connections: list[_Live] = []

    async def notify(self, channel, fields):
        for live in self.connections:
            if channel in live.channels:
                live.inbox.put_nowait((channel, dict(fields)))

    async def open_live(self):
        live = _Live()
        self.connections.append(live)
        return live


class _Live:
    def __init__(self) -> None:
        self.channels: set[str] = set()
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def subscribe(self, channel):
        self.channels.add(channel)

    async def unsubscribe(self, channel):
        self.channels.discard(channel)

    async def next_message(self, timeout_seconds):
        try:
            return await asyncio.wait_for(self.inbox.get(), timeout_seconds)
        except TimeoutError:
            return None

    async def aclose(self):
        self.closed = True


def _event(workspace_id: str) -> StreamEvent:
    return StreamEvent(
        type="order.paid",
        source="test",
        data={},
        stream_id=uuid4(),
        workspace_id=workspace_id,
        created_by="u",
        event_key="k",
        received_at=datetime.now(UTC),
    )


async def test_a_page_hears_only_its_workspace_and_both_kinds_of_notice():
    broker = _Broker()
    hub = EventNoticesHub(broker)
    notices = BrokerEventNotices(broker)
    mine, other = _event("ws-1"), _event("ws-2")
    try:
        async with hub.subscribe("ws-1") as queue, hub.subscribe("ws-2") as theirs:
            await notices.recorded(mine)
            await notices.processing(mine)
            await notices.recorded(other)
            got = [await asyncio.wait_for(queue.get(), 1) for _ in range(2)]
            assert await asyncio.wait_for(theirs.get(), 1) == EventNotice(
                kind=NoticeKind.RECORDED, event_id=other.id, stream_id=other.stream_id
            )
        assert got == [
            EventNotice(kind=NoticeKind.RECORDED, event_id=mine.id, stream_id=mine.stream_id),
            EventNotice(kind=NoticeKind.PROCESSING, event_id=mine.id, stream_id=mine.stream_id),
        ]
        assert queue.empty()
        (live,) = broker.connections
        assert live.channels == set()
    finally:
        await hub.aclose()
    assert broker.connections[0].closed


async def test_the_channel_carries_the_namespace_free_workspace_name():
    broker = _Broker()
    live = await broker.open_live()
    await live.subscribe("streams.live.ws-9")
    await BrokerEventNotices(broker).recorded(_event("ws-9"))
    channel, fields = await live.next_message(1)
    assert channel == "streams.live.ws-9"
    assert fields["type"] == "event.recorded"


async def test_closing_the_hub_ends_every_open_page():
    broker = _Broker()
    hub = EventNoticesHub(broker)
    async with hub.subscribe("ws-1") as queue:
        await hub.aclose()
        assert await asyncio.wait_for(queue.get(), 1) is None


async def test_a_page_too_far_behind_has_its_stream_ended(monkeypatch):
    monkeypatch.setattr("agentarea_streams.infrastructure.live.QUEUE_LIMIT", 2)
    broker = _Broker()
    hub = EventNoticesHub(broker)
    notices = BrokerEventNotices(broker)
    event = _event("ws-1")
    try:
        async with hub.subscribe("ws-1") as queue:
            for _ in range(3):
                await notices.processing(event)
            await asyncio.sleep(0.2)
            assert await asyncio.wait_for(queue.get(), 1) is None
    finally:
        await hub.aclose()
