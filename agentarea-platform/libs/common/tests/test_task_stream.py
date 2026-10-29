"""A task's feed: the log from a position, then the tasks.events tail and live signals (ADR-0043 §8)."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import pytest
from agentarea_common.broker.interface import BrokerMessage
from agentarea_common.broker.topics import BUS_RETENTION, TASK_EVENTS
from agentarea_common.events.adapters.redis_streams import decode, encode
from agentarea_common.events.task_stream import (
    TaskEventEnvelope,
    TaskEventsHub,
    broadcast_live,
    envelope_from_event,
    iter_task_event_feed,
    publish_task_event,
    task_event,
)

_TASK = "11111111-1111-1111-1111-111111111111"
_OTHER = "22222222-2222-2222-2222-222222222222"
_TERMINAL = frozenset({"task.completed"})


def _uid(n: int) -> str:
    return f"00000000-0000-0000-0000-{n:012d}"


def _env(seq: int | None, event_type: str = "turn.started", **data) -> TaskEventEnvelope:
    return TaskEventEnvelope(
        event_type=event_type, event_id=_uid(seq or 999), timestamp=None, data=data, seq=seq
    )


class _FakeHub:
    """A hub whose live queue already holds what the tail will deliver."""

    def __init__(self, live: list[TaskEventEnvelope]) -> None:
        self.live = live
        self.subscribed: list[str] = []

    @asynccontextmanager
    async def subscribe(self, task_id: str):
        self.subscribed.append(task_id)
        queue: asyncio.Queue[TaskEventEnvelope] = asyncio.Queue()
        for env in self.live:
            queue.put_nowait(env)
        yield queue


def _snapshot(*envs: TaskEventEnvelope):
    async def loader():
        for env in envs:
            yield env

    return loader


async def _feed(hub, snapshot, **kwargs) -> list[TaskEventEnvelope]:
    kwargs.setdefault("max_wall_time_seconds", 1)
    return [
        env
        async for env in iter_task_event_feed(
            hub=hub, task_id=_TASK, snapshot=snapshot, terminal_types=_TERMINAL, **kwargs
        )
    ]


async def test_the_log_then_the_tail_dropping_positions_already_sent():
    hub = _FakeHub([_env(2), _env(3), _env(4, "task.completed")])
    out = await _feed(hub, _snapshot(_env(1), _env(2)))
    assert [e.seq for e in out] == [1, 2, 3, 4]
    assert hub.subscribed == [_TASK]


async def test_live_only_signals_have_no_position_and_pass():
    hub = _FakeHub([_env(None, "llm.call.chunk"), _env(3, "task.completed")])
    out = await _feed(hub, _snapshot(_env(1)))
    assert [(e.event_type, e.seq) for e in out] == [
        ("turn.started", 1),
        ("llm.call.chunk", None),
        ("task.completed", 3),
    ]


async def test_a_finished_task_ends_after_its_log():
    hub = _FakeHub([_env(9)])
    out = await _feed(
        hub, _snapshot(_env(1), _env(2, "task.completed")), run_open=_returns(False)
    )
    assert [e.seq for e in out] == [1, 2]


async def test_a_task_with_a_new_run_keeps_tailing_after_its_log():
    hub = _FakeHub([_env(3), _env(4, "task.completed")])
    out = await _feed(hub, _snapshot(_env(1), _env(2, "task.completed")), run_open=_returns(True))
    assert [e.seq for e in out] == [1, 2, 3, 4]


async def test_a_later_task_started_reopens_a_closed_history():
    hub = _FakeHub([_env(4), _env(5, "task.completed")])
    out = await _feed(
        hub,
        _snapshot(_env(1, "task.completed"), _env(2, "task.started"), _env(3)),
        run_open=_returns(False),
    )
    assert [e.seq for e in out] == [1, 2, 3, 4, 5]


async def test_after_a_position_the_feed_tails_the_next_turn_past_a_finished_one():
    # A message was just handed to a task whose last turn finished: its run has
    # not reported yet, and the turn before must neither replay nor close the feed.
    hub = _FakeHub([_env(2, "task.completed"), _env(3), _env(4, "task.completed")])
    out = await _feed(
        hub,
        _snapshot(_env(1), _env(2, "task.completed")),
        after_seq=2,
        run_open=_returns(False),
    )
    assert [e.seq for e in out] == [3, 4]


async def test_a_conversation_waiting_for_a_follow_up_stays_open():
    hub = _FakeHub([_env(3, "message.received"), _env(4, "task.completed")])
    out = await _feed(
        hub,
        _snapshot(_env(1), _env(2, "task.completed", execution_status="waiting")),
        follow_execution=True,
    )
    assert [e.seq for e in out] == [1, 2, 3, 4]


async def test_a_resume_starts_after_the_position_the_client_has():
    hub = _FakeHub([_env(2), _env(3, "task.completed")])
    out = await _feed(hub, _snapshot(_env(2)), resume_after=_env(1))
    assert [e.seq for e in out] == [2, 3]


async def test_excluded_types_are_dropped():
    hub = _FakeHub([_env(None, "llm.call.chunk"), _env(2, "task.completed")])
    out = await _feed(hub, _snapshot(_env(1)), exclude_types=frozenset({"llm.call.chunk"}))
    assert [e.event_type for e in out] == ["turn.started", "task.completed"]


def _returns(value: bool):
    async def check() -> bool:
        return value

    return check


class _RecordingBroker:
    def __init__(self) -> None:
        self.submitted: list[tuple[str, dict[str, str], object]] = []
        self.notified: list[tuple[str, dict[str, str]]] = []

    async def submit(self, stream, fields, *, retention):
        self.submitted.append((stream, dict(fields), retention))
        return "1-0"

    async def notify(self, channel, fields):
        self.notified.append((channel, dict(fields)))


def _event(event_type: str, seq: int | None = 1, task_id: str = _TASK):
    return task_event(
        task_id=task_id,
        workspace_id="ws",
        event_type=event_type,
        event_id=_uid(seq or 7),
        timestamp=datetime.now(UTC),
        data={"n": 1},
        seq=seq,
    )


async def test_a_stored_event_goes_to_tasks_events_with_its_position_and_retention():
    broker = _RecordingBroker()
    await publish_task_event(broker, _event("tool.result", seq=5))
    ((stream, fields, retention),) = broker.submitted
    assert (stream, retention) == (TASK_EVENTS, BUS_RETENTION)
    decoded = decode(fields)
    assert decoded.subject == _TASK
    assert envelope_from_event(decoded).seq == 5
    assert decoded.extensions["workspace"] == "ws"


async def test_a_live_only_signal_is_broadcast_never_stored():
    broker = _RecordingBroker()
    await broadcast_live(broker, _event("llm.call.chunk", seq=None))
    assert broker.submitted == []
    assert [channel for channel, _ in broker.notified] == [f"tasks.live.{_TASK}"]
    with pytest.raises(ValueError, match="live-only"):
        await publish_task_event(broker, _event("llm.call.chunk", seq=None))
    with pytest.raises(ValueError, match="stored"):
        await broadcast_live(broker, _event("tool.result"))


class _HubBroker:
    """One scripted tail batch and a live connection that records subscriptions."""

    def __init__(self, messages: list[BrokerMessage]) -> None:
        self._messages = messages
        self.channels: list[str] = []
        self.unsubscribed: list[str] = []

    async def last_id(self, stream):
        return "5-0"

    async def tail(self, stream, last_id="$", block_ms=5000, count=100):
        assert last_id == "5-0" or self._messages == []
        if self._messages:
            batch, self._messages = self._messages, []
            return batch[-1].id, batch
        await asyncio.sleep(0.01)
        return last_id, []

    async def open_live(self):
        broker = self

        class _Live:
            async def subscribe(self, channel):
                broker.channels.append(channel)

            async def unsubscribe(self, channel):
                broker.unsubscribed.append(channel)

            async def next_message(self, timeout_seconds):
                await asyncio.sleep(0.01)
                return None

            async def aclose(self):
                pass

        return _Live()


async def test_the_hub_hands_each_feed_only_its_task_events_from_the_newest_entry_on():
    mine = BrokerMessage(id="6-0", fields=encode(_event("tool.result", seq=3)))
    other = BrokerMessage(id="7-0", fields=encode(_event("tool.result", seq=1, task_id=_OTHER)))
    broker = _HubBroker([other, mine])
    hub = TaskEventsHub(broker, block_ms=10)
    try:
        async with hub.subscribe(_TASK) as queue:
            got = await asyncio.wait_for(queue.get(), timeout=2)
            assert (got.seq, got.event_type) == (3, "tool.result")
            assert queue.empty()
        assert broker.channels == [f"tasks.live.{_TASK}"]
        assert broker.unsubscribed == [f"tasks.live.{_TASK}"]
    finally:
        await hub.aclose()
