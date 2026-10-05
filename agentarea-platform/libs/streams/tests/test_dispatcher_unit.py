from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application.dispatcher import StreamDispatcher, backoff
from agentarea_streams.application.forward import ForwardHandler
from agentarea_streams.domain import (
    AppendResult,
    EventFilter,
    JournaledEvent,
    StreamQuotaExceededError,
    SubscriptionKind,
    SubscriptionView,
    Verdict,
)


def test_backoff_doubles_and_caps_at_five_minutes():
    assert backoff(1) == timedelta(seconds=1)
    assert backoff(4) == timedelta(seconds=8)
    assert backoff(30) == timedelta(seconds=300)


def _forward(outputs: list[UUID]) -> SubscriptionView:
    return SubscriptionView(
        id=uuid4(),
        workspace_id="ws",
        created_by="u",
        stream_id=uuid4(),
        kind=SubscriptionKind.FORWARD,
        trigger_id=None,
        filter=EventFilter(),
        output_stream_ids=outputs,
    )


def _event(depth: int = 0) -> JournaledEvent:
    now = datetime.now(UTC)
    return JournaledEvent(
        type="push",
        source="test",
        data={"n": 1},
        stream_id=uuid4(),
        sequence=7,
        event_key="e1",
        received_at=now,
        depth=depth,
    )


class _Journal:
    appended: list[UUID] = []
    fail_with: Exception | None = None

    def __init__(self, session, user_context, settings):
        self.user_context = user_context

    async def append(self, stream_id, event, *, event_key, depth):
        if _Journal.fail_with is not None:
            raise _Journal.fail_with
        _Journal.appended.append(stream_id)
        return AppendResult(sequence=100 + len(_Journal.appended), appended=True)


@pytest.fixture
def journal():
    _Journal.appended = []
    _Journal.fail_with = None
    with patch("agentarea_streams.application.forward.StreamJournal", _Journal):
        yield _Journal


async def test_a_forward_appends_to_its_outputs_in_stream_id_order(journal):
    outputs = [UUID(int=3), UUID(int=1), UUID(int=2)]
    result = await ForwardHandler(EventStreamSettings()).handle(
        _forward(outputs), _event(), MagicMock()
    )
    assert journal.appended == [UUID(int=1), UUID(int=2), UUID(int=3)]
    assert result.verdict is Verdict.REACTED and len(result.derived_sequences) == 3


async def test_a_forward_past_the_causation_depth_is_an_error_and_appends_nothing(journal):
    settings = EventStreamSettings(FORWARD_DEPTH=2)
    result = await ForwardHandler(settings).handle(
        _forward([uuid4()]), _event(depth=2), MagicMock()
    )
    assert result.verdict is Verdict.ERROR and "causation depth 3 exceeds 2" in (
        result.reason or ""
    )
    assert journal.appended == []


async def test_a_forward_over_the_write_quota_fails_so_the_dispatcher_retries_it(journal):
    journal.fail_with = StreamQuotaExceededError("ws", 1)
    with pytest.raises(StreamQuotaExceededError):
        await ForwardHandler(EventStreamSettings()).handle(
            _forward([uuid4()]), _event(), MagicMock()
        )


def test_a_dispatcher_refuses_to_start_without_a_handler_for_every_kind():
    with pytest.raises(ValueError, match="forward"):
        StreamDispatcher(
            session_factory=MagicMock(),
            settings=EventStreamSettings(),
            handlers={SubscriptionKind.TRIGGER: MagicMock()},
            waker=MagicMock(),
        )
