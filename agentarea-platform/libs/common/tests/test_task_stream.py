"""Tests for the task-event read side (catch-up + live), ADR-0018."""

import pytest
from agentarea_common.events.adapters.redis_streams import topic_for
from agentarea_common.events.ports import IntegrationEvent
from agentarea_common.events.task_stream import (
    TASK_STREAM_MAXLEN,
    TaskEventEnvelope,
    iter_task_event_feed,
    publish_task_event,
    task_stream_name,
)

_TASK = "task-123"
_TERMINAL = frozenset({"TaskCompleted"})


def _uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


class _FakeStream:
    """EventStream stub yielding scripted IntegrationEvents then stopping."""

    def __init__(self, events: list[IntegrationEvent]) -> None:
        self._events = events
        self.read_args: dict = {}

    async def read(self, *, stream, from_offset="0"):
        self.read_args = {"stream": stream, "from_offset": from_offset}
        for e in self._events:
            yield e


def _env(n: int, event_type: str = "Step") -> TaskEventEnvelope:
    return TaskEventEnvelope(event_type=event_type, event_id=_uid(n), timestamp=None, data={})


def _evt(n: int, event_type: str = "Step") -> IntegrationEvent:
    return IntegrationEvent(id=_uid(n), type=event_type, source="w", subject=_TASK, data={})


async def _collect(agen) -> list[TaskEventEnvelope]:
    return [e async for e in agen]


async def _snapshot_of(*envs):
    async def _loader():
        return list(envs)

    return _loader


def test_task_stream_name():
    assert task_stream_name("abc") == "task.abc"


@pytest.mark.asyncio
async def test_feed_replays_snapshot_then_live():
    snapshot = await _snapshot_of(_env(1), _env(2))
    stream = _FakeStream([_evt(3), _evt(4, "TaskCompleted")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=_TERMINAL
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(2), _uid(3), _uid(4)]
    # Live tail replays the retained stream from the start.
    assert stream.read_args == {"stream": task_stream_name(_TASK), "from_offset": "0"}


@pytest.mark.asyncio
async def test_feed_dedups_overlap_between_snapshot_and_stream():
    # Event 2 is in the DB snapshot AND replayed by the stream — emit once.
    snapshot = await _snapshot_of(_env(1), _env(2))
    stream = _FakeStream([_evt(2), _evt(3, "TaskCompleted")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=_TERMINAL
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(2), _uid(3)]


@pytest.mark.asyncio
async def test_feed_stops_in_snapshot_when_task_already_terminal():
    # Task already finished: terminal is in the snapshot, never touch the stream.
    snapshot = await _snapshot_of(_env(1), _env(2, "TaskCompleted"))
    stream = _FakeStream([_evt(99)])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=_TERMINAL
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(2)]
    assert stream.read_args == {}  # stream never read


@pytest.mark.asyncio
async def test_feed_drops_excluded_types_from_snapshot_and_live():
    # SSE excludes LLMCallChunk (stream-only, high volume) to preserve behaviour;
    # terminal detection must still fire.
    snapshot = await _snapshot_of(_env(1), _env(2, "LLMCallChunk"))
    stream = _FakeStream([_evt(3, "LLMCallChunk"), _evt(4, "TaskCompleted")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=_TERMINAL,
            exclude_types=frozenset({"LLMCallChunk"}),
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(4)]


@pytest.mark.asyncio
async def test_publish_task_event_uses_bounded_stream():
    captured = {}

    class _Broker:
        async def submit(self, stream, fields, *, maxlen=None):
            captured["stream"] = stream
            captured["maxlen"] = maxlen
            captured["fields"] = fields
            return "1-0"

    await publish_task_event(
        _Broker(),
        task_id=_TASK,
        event_type="TaskCompleted",
        data={"result": "ok"},
        event_id=_uid(1),
    )
    assert captured["stream"] == topic_for(task_stream_name(_TASK))
    assert captured["maxlen"] == TASK_STREAM_MAXLEN
    # Round-trips back through the same codec the reader uses.
    from agentarea_common.events.adapters.redis_streams import decode

    restored = decode(captured["fields"])
    assert restored.type == "TaskCompleted"
    assert restored.subject == _TASK
    assert restored.data == {"result": "ok"}


@pytest.mark.asyncio
async def test_publish_task_event_swallows_broker_errors():
    class _BadBroker:
        async def submit(self, stream, fields, *, maxlen=None):
            raise RuntimeError("redis down")

    # Best-effort: must not raise (durable record is the DB).
    await publish_task_event(_BadBroker(), task_id=_TASK, event_type="Step", data={})
