"""The workspace events feed's live tail: notices become SSE frames for the page."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from agentarea_api.api.v1.stream_event_feed import FeedEventResponse, iter_live_feed
from agentarea_streams.domain.processing import Processing, ProcessingStatus, ProcessingTask
from agentarea_streams.infrastructure.live import EventNotice, NoticeKind


def _item(event_id, stream_id, status=ProcessingStatus.QUEUED) -> FeedEventResponse:
    now = datetime.now(UTC)
    return FeedEventResponse(
        sequence=7,
        event_id=event_id,
        stream_id=stream_id,
        source_id=None,
        source_type="generic_webhook",
        kind="order.paid",
        key="k",
        session_key=None,
        sender="alice",
        received_at=now,
        occurred_at=now,
        depth=0,
        correlation_id=None,
        causation_id=None,
        attachments=0,
        processing=Processing(
            status=status,
            subscribers=None if status is ProcessingStatus.QUEUED else 1,
            reacted=0 if status is ProcessingStatus.QUEUED else 1,
            skipped=0,
            errors=0,
            tasks=[]
            if status is ProcessingStatus.QUEUED
            else [ProcessingTask(id=uuid4(), status="running")],
        ),
    )


def _frames(raw: list[str]) -> list[tuple[str, dict]]:
    out = []
    for frame in raw:
        lines = dict(line.split(": ", 1) for line in frame.strip().split("\n"))
        out.append((lines["event"], json.loads(lines["data"])))
    return out


async def test_notices_on_readable_streams_become_recorded_and_processing_frames():
    readable, hidden = uuid4(), uuid4()
    shown, filtered_out, secret = uuid4(), uuid4(), uuid4()
    queue: asyncio.Queue = asyncio.Queue()
    for notice in (
        EventNotice(kind=NoticeKind.RECORDED, event_id=secret, stream_id=hidden),
        EventNotice(kind=NoticeKind.RECORDED, event_id=filtered_out, stream_id=readable),
        EventNotice(kind=NoticeKind.RECORDED, event_id=shown, stream_id=readable),
        EventNotice(kind=NoticeKind.PROCESSING, event_id=shown, stream_id=readable),
    ):
        queue.put_nowait(notice)
    loads = []
    state = {"status": ProcessingStatus.QUEUED}

    async def load(event_id):
        loads.append(event_id)
        if event_id == filtered_out:
            return None
        item = _item(event_id, readable, state["status"])
        state["status"] = ProcessingStatus.HANDLED
        return item

    @asynccontextmanager
    async def subscribe():
        yield queue

    feed = iter_live_feed(subscribe=subscribe, streams=[readable], load=load)
    assert (await anext(feed)).startswith(":")
    frames = _frames([await anext(feed), await anext(feed)])
    await feed.aclose()

    assert secret not in loads
    (recorded, recorded_data), (processing, processing_data) = frames
    assert recorded == "event.recorded"
    assert recorded_data["event_id"] == str(shown)
    assert recorded_data["processing"]["status"] == "queued"
    assert "data" not in recorded_data
    assert processing == "event.processing"
    assert processing_data["event_id"] == str(shown)
    assert processing_data["processing"]["status"] == "handled"
    assert processing_data["processing"]["tasks"][0]["status"] == "running"


async def test_the_tail_ends_when_the_hub_closes():
    queue: asyncio.Queue = asyncio.Queue()
    queue.put_nowait(None)

    @asynccontextmanager
    async def subscribe():
        yield queue

    async def load(event_id):
        raise AssertionError("nothing to load")

    frames = [f async for f in iter_live_feed(subscribe=subscribe, streams=[], load=load)]
    assert len(frames) == 1
    assert frames[0].startswith(":")


def test_a_reaction_whose_task_failed_still_names_the_task():
    from types import SimpleNamespace

    from agentarea_api.api.v1.stream_event_feed import _started_task

    task_id = uuid4()
    assert _started_task(SimpleNamespace(verdict="reacted", status="failed", task_id=task_id)) == (
        task_id
    )
    assert _started_task(SimpleNamespace(verdict="skipped", status="skipped", task_id=None)) is None
