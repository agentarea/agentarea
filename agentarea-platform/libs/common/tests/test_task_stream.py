"""Tests for the task-event read side (catch-up + live), ADR-0018."""

from datetime import UTC, datetime, timedelta

import pytest
from agentarea_common.events.adapters.redis_streams import topic_for
from agentarea_common.events.contract import ensure_terminal_message
from agentarea_common.events.ports import IntegrationEvent
from agentarea_common.events.task_stream import (
    TASK_STREAM_MAXLEN,
    TASK_STREAM_TTL_SECONDS,
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
        for env in envs:
            yield env

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
async def test_feed_includes_chunks_when_not_excluded():
    # Default (no exclude_types): chunks and finals both yielded, in order.
    snapshot = await _snapshot_of(_env(1), _env(2, "LLMCallChunk"))
    stream = _FakeStream([_evt(3, "LLMCallChunk"), _evt(4, "TaskCompleted")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=_TERMINAL
        )
    )
    assert [(e.event_id, e.event_type) for e in out] == [
        (_uid(1), "Step"),
        (_uid(2), "LLMCallChunk"),
        (_uid(3), "LLMCallChunk"),
        (_uid(4), "TaskCompleted"),
    ]


@pytest.mark.asyncio
async def test_feed_excludes_chunks_still_terminates_with_finals():
    # With chunks excluded: chunks dropped, finals + terminal still yielded and
    # the feed terminates on the terminal event.
    snapshot = await _snapshot_of(_env(1, "LLMCallChunk"), _env(2, "Step"))
    stream = _FakeStream(
        [_evt(3, "LLMCallChunk"), _evt(4, "Step"), _evt(5, "TaskCompleted"), _evt(6, "Step")]
    )
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=_TERMINAL,
            exclude_types=frozenset({"LLMCallChunk"}),
        )
    )
    assert [e.event_id for e in out] == [_uid(2), _uid(4), _uid(5)]
    assert [e.event_type for e in out] == ["Step", "Step", "TaskCompleted"]


@pytest.mark.asyncio
async def test_catch_up_replay_equals_live_replay():
    # The same event set delivered via snapshot-only vs live-only yields the
    # same normalized (id, type) sequence.
    events = [(1, "Step"), (2, "LLMCallChunk"), (3, "Step"), (4, "TaskCompleted")]

    snapshot_only = await _snapshot_of(*[_env(n, t) for n, t in events])
    via_snapshot = await _collect(
        iter_task_event_feed(
            stream=_FakeStream([]),
            task_id=_TASK,
            snapshot=snapshot_only,
            terminal_types=_TERMINAL,
        )
    )

    empty_snapshot = await _snapshot_of()
    via_live = await _collect(
        iter_task_event_feed(
            stream=_FakeStream([_evt(n, t) for n, t in events]),
            task_id=_TASK,
            snapshot=empty_snapshot,
            terminal_types=_TERMINAL,
        )
    )

    normalized = [(e.event_id, e.event_type) for e in via_snapshot]
    assert normalized == [(e.event_id, e.event_type) for e in via_live]
    assert normalized == [(_uid(n), t) for n, t in events]


@pytest.mark.asyncio
async def test_publish_task_event_uses_bounded_stream():
    captured = {}

    class _Broker:
        async def submit(self, stream, fields, *, maxlen=None, ttl_seconds=None):
            captured["stream"] = stream
            captured["maxlen"] = maxlen
            captured["ttl_seconds"] = ttl_seconds
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
    # A finished task's stream must not outlive its readers.
    assert captured["ttl_seconds"] == TASK_STREAM_TTL_SECONDS
    # Round-trips back through the same codec the reader uses.
    from agentarea_common.events.adapters.redis_streams import decode

    restored = decode(captured["fields"])
    assert restored.type == "TaskCompleted"
    assert restored.subject == _TASK
    assert restored.data == {"result": "ok"}


@pytest.mark.asyncio
async def test_feed_terminates_on_canonical_terminal_row():
    # New canonical row: terminal_types are the canonical task.* names; a
    # persisted "task.completed" row must end the feed.
    canonical_terminal = frozenset({"task.completed", "task.failed", "task.cancelled"})
    snapshot = await _snapshot_of(_env(1), _env(2, "task.completed"))
    stream = _FakeStream([_evt(99)])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=canonical_terminal
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(2)]
    assert stream.read_args == {}


@pytest.mark.asyncio
async def test_feed_terminates_on_canonical_history():
    # Canonical rows across the snapshot/live boundary; terminal detection fires
    # on the canonical "task.completed" row.
    canonical_terminal = frozenset({"task.completed", "task.failed", "task.cancelled"})
    snapshot = await _snapshot_of(_env(1, "task.started"), _env(2, "tool.result"))
    stream = _FakeStream([_evt(3, "llm.call.completed"), _evt(4, "task.completed"), _evt(5)])
    out = await _collect(
        iter_task_event_feed(
            stream=stream, task_id=_TASK, snapshot=snapshot, terminal_types=canonical_terminal
        )
    )
    assert [e.event_id for e in out] == [_uid(1), _uid(2), _uid(3), _uid(4)]


@pytest.mark.asyncio
@pytest.mark.parametrize(("follow_execution", "expected"), [(False, [1]), (True, [1, 2, 3])])
async def test_web_feed_follows_execution_while_a2a_ends_at_completed_turn(
    follow_execution, expected
):
    turn = TaskEventEnvelope(
        event_type="task.completed",
        event_id=_uid(1),
        timestamp=None,
        data={"execution_status": "waiting"},
    )
    snapshot = await _snapshot_of(turn)
    stream = _FakeStream(
        [
            _evt(2, "llm.call.started"),
            _evt(3, "execution.finished"),
            _evt(4, "unused"),
        ]
    )
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=frozenset({"task.completed", "execution.finished"}),
            follow_execution=follow_execution,
        )
    )
    assert [event.event_id for event in out] == [_uid(n) for n in expected]


@pytest.mark.asyncio
async def test_web_feed_keeps_live_follow_up_wait_open_until_execution_finishes():
    snapshot = await _snapshot_of(_env(1, "task.started"))
    stream = _FakeStream(
        [
            IntegrationEvent(
                id=_uid(2),
                type="task.completed",
                source="w",
                subject=_TASK,
                data={"execution_status": "waiting"},
            ),
            _evt(3, "execution.finished"),
            _evt(4, "unused"),
        ]
    )
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=frozenset({"task.completed", "execution.finished"}),
            follow_execution=True,
        )
    )
    assert [event.event_type for event in out] == [
        "task.started",
        "task.completed",
        "execution.finished",
    ]


@pytest.mark.asyncio
async def test_feed_excludes_chunks_by_canonical_name():
    # exclude_types passed as canonical "llm.call.chunk" drops chunk rows.
    canonical_terminal = frozenset({"task.completed"})
    snapshot = await _snapshot_of(_env(1, "llm.call.chunk"), _env(2, "llm.call.chunk"))
    stream = _FakeStream([_evt(3, "llm.call.chunk"), _evt(4, "task.completed")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=canonical_terminal,
            exclude_types=frozenset({"llm.call.chunk"}),
        )
    )
    assert [e.event_id for e in out] == [_uid(4)]


def test_terminal_message_added_for_completed():
    # A terminal completed event with no message gets a human-readable one.
    data = ensure_terminal_message("task.completed", {"final_response": "All done."})
    assert data["message"] == "All done."


def test_terminal_message_added_for_failed_with_reason():
    data = ensure_terminal_message(
        "task.failed", {"error": "Provider quota exceeded", "error_type": "QuotaExceeded"}
    )
    assert data["message"]
    assert data["reason"] == "Provider quota exceeded"


def test_terminal_message_added_for_cancelled():
    data = ensure_terminal_message("task.cancelled", {})
    assert data["message"]
    assert data["reason"]


def test_terminal_message_preserved_when_present():
    # Existing message is never overwritten (additive).
    data = ensure_terminal_message(
        "task.completed", {"message": "custom", "final_response": "ignored"}
    )
    assert data["message"] == "custom"


def test_terminal_message_noop_for_non_terminal():
    # Non-terminal events pass through unchanged.
    src = {"chunk": "hi"}
    data = ensure_terminal_message("llm.call.chunk", src)
    assert data == src
    assert "message" not in data


def test_terminal_message_accepts_prefixed_and_canonical():
    prefixed = ensure_terminal_message("workflow.task.cancelled", {})
    assert prefixed["message"]
    canonical = ensure_terminal_message("task.cancelled", {})
    assert canonical["message"]


@pytest.mark.asyncio
async def test_publish_task_event_raises_broker_errors():
    class _BadBroker:
        async def submit(self, stream, fields, *, maxlen=None, ttl_seconds=None):
            raise RuntimeError("redis down")

    # The caller decides: the workflow-event activity retries the whole batch,
    # the chunk publisher drops a best-effort snapshot.
    with pytest.raises(RuntimeError, match="redis down"):
        await publish_task_event(_BadBroker(), task_id=_TASK, event_type="Step", data={})


_T0 = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _at(n: int, seconds: int, event_type: str = "Step", data: dict | None = None):
    return TaskEventEnvelope(
        event_type=event_type,
        event_id=_uid(n),
        timestamp=(_T0 + timedelta(seconds=seconds)).isoformat(),
        data=data or {},
    )


def _live_at(n: int, seconds: int, event_type: str = "Step") -> IntegrationEvent:
    return IntegrationEvent(
        id=_uid(n),
        type=event_type,
        source="w",
        subject=_TASK,
        time=_T0 + timedelta(seconds=seconds),
        data={},
    )


@pytest.mark.asyncio
async def test_resumed_feed_skips_retained_stream_entries_the_client_already_saw():
    # The client saw event 2; the snapshot loader returns only what came after
    # it, and the retained stream still replays 1 and 2 from offset 0.
    cursor = _at(2, 2)
    snapshot = await _snapshot_of(_at(3, 3))
    stream = _FakeStream([_live_at(1, 1), _live_at(2, 2), _live_at(3, 3), _live_at(4, 4)])
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=_TERMINAL,
            resume_after=cursor,
        )
    )
    assert [e.event_id for e in out] == [_uid(3), _uid(4)]


@pytest.mark.asyncio
async def test_resume_after_a_terminal_event_ends_the_feed_without_tailing():
    cursor = _at(5, 5, "TaskCompleted")
    snapshot = await _snapshot_of()
    stream = _FakeStream([_live_at(6, 6)])
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=_TERMINAL,
            resume_after=cursor,
        )
    )
    assert out == []
    assert stream.read_args == {}


@pytest.mark.asyncio
async def test_resume_after_a_waiting_turn_keeps_following_the_execution():
    cursor = _at(1, 1, "task.completed", {"execution_status": "waiting"})
    snapshot = await _snapshot_of()
    stream = _FakeStream([_live_at(1, 1, "task.completed"), _live_at(2, 2, "execution.finished")])
    out = await _collect(
        iter_task_event_feed(
            stream=stream,
            task_id=_TASK,
            snapshot=snapshot,
            terminal_types=frozenset({"task.completed", "execution.finished"}),
            follow_execution=True,
            resume_after=cursor,
        )
    )
    assert [e.event_id for e in out] == [_uid(2)]
