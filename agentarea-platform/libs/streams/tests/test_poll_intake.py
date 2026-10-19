"""Items the event-service polled reach their stream through the same ingest as a webhook."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_common.broker import BrokerMessage
from agentarea_streams.application.poll_intake import (
    GAP_KIND,
    MalformedItemError,
    PolledItemConsumer,
    parse_message,
)
from agentarea_streams.domain.errors import StreamNotFoundError
from agentarea_streams.domain.models import AppendResult
from agentarea_streams.domain.source_types import SourceTypeEntry

ENTRY = SourceTypeEntry.model_validate(
    {
        "slug": "feedy",
        "name": "Feedy",
        "delivery": "poll",
        "poll": {"transport": "feed", "request": {"url": "{config.url}"}},
        "event": {"kind": "item", "key": "{body:id}"},
    }
)


class _Broker:
    def __init__(self) -> None:
        self.acked: list[str] = []
        self.dead_letters: list[tuple[str, dict[str, str]]] = []
        self.groups: list[tuple[str, str]] = []

    async def ensure_group(self, stream: str, group: str, start: str = "$") -> None:
        self.groups.append((stream, group))

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        self.acked.append(message_id)

    async def submit(self, stream: str, fields: dict[str, str], *, retention) -> str:
        self.dead_letters.append((stream, dict(fields)))
        return "dlq-1"


class _Session:
    def __init__(self, source) -> None:
        self.source = source

    async def get(self, _model, ident):
        return self.source if self.source is not None and self.source.id == ident else None


class _Ingest:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    async def __call__(self, session, source, entry, **kwargs) -> AppendResult:
        self.calls.append({"source": source, "entry": entry, **kwargs})
        if self.fail is not None:
            raise self.fail
        return AppendResult(event_id=uuid4(), appended=True)


def _source():
    return SimpleNamespace(id=uuid4(), webhook_type="feedy", stream_id=uuid4())


def _consumer(broker, source, ingest, *, entry=ENTRY, attempts=20) -> PolledItemConsumer:
    @asynccontextmanager
    async def session_scope():
        yield _Session(source)

    async def load_entry(_session, slug):
        return entry if entry is not None and slug == entry.slug else None

    return PolledItemConsumer(
        broker,  # type: ignore[arg-type]
        session_scope=session_scope,  # type: ignore[arg-type]
        ingest=ingest,
        consumer_id="c1",
        load_entry=load_entry,  # type: ignore[arg-type]
        max_delivery_attempts=attempts,
    )


def _message(source_id, *, kind="item", item=None, delivery_count=1) -> BrokerMessage:
    return BrokerMessage(
        id="1-0",
        fields={
            "source_id": str(source_id),
            "kind": kind,
            "item": json.dumps(item if item is not None else {"id": "n1", "title": "x"}),
            "received_at": "2026-10-15T10:00:00.123456789Z",
        },
        delivery_count=delivery_count,
    )


async def test_an_item_is_ingested_as_its_source_with_no_headers_and_acked():
    broker, source, ingest = _Broker(), _source(), _Ingest()
    await _consumer(broker, source, ingest).handle(_message(source.id))

    (call,) = ingest.calls
    assert call["source"] is source
    assert call["entry"] is ENTRY
    assert call["body"] == {"id": "n1", "title": "x"}
    assert call["headers"] == {}
    assert call["received_at"] == datetime(2026, 10, 15, 10, 0, 0, 123456, tzinfo=UTC)
    assert call["kind_override"] is None
    assert call["key_override"] is None
    assert broker.acked == ["1-0"]


async def test_a_gap_becomes_a_source_gap_event_keyed_by_when_it_was_seen():
    broker, source, ingest = _Broker(), _source(), _Ingest()
    message = _message(source.id, kind="gap", item={"reason": "mailbox renumbered"})
    await _consumer(broker, source, ingest).handle(message)

    (call,) = ingest.calls
    assert call["kind_override"] == GAP_KIND
    assert call["key_override"] == "gap:2026-10-15T10:00:00.123456+00:00"
    assert call["body"] == {"reason": "mailbox renumbered"}
    assert broker.acked == ["1-0"]


async def test_a_failed_ingest_stays_pending_for_redelivery():
    broker, source = _Broker(), _source()
    ingest = _Ingest(fail=RuntimeError("bus down"))
    await _consumer(broker, source, ingest).handle(_message(source.id))

    assert broker.acked == []
    assert broker.dead_letters == []


async def test_past_the_delivery_cap_it_is_dead_lettered():
    broker, source, ingest = _Broker(), _source(), _Ingest()
    await _consumer(broker, source, ingest, attempts=3).handle(
        _message(source.id, delivery_count=4)
    )

    assert ingest.calls == []
    ((stream, fields),) = broker.dead_letters
    assert stream == "streams.ingest.ingest.dlq"
    assert "gave up" in fields["fatal_reason"]
    assert broker.acked == ["1-0"]


async def test_a_source_type_missing_from_the_catalog_is_dead_lettered():
    broker, source, ingest = _Broker(), _source(), _Ingest()
    await _consumer(broker, source, ingest, entry=None).handle(_message(source.id))

    assert ingest.calls == []
    assert "not in the catalog" in broker.dead_letters[0][1]["fatal_reason"]
    assert broker.acked == ["1-0"]


async def test_an_item_of_a_deleted_source_is_dropped():
    broker, ingest = _Broker(), _Ingest()
    await _consumer(broker, None, ingest).handle(_message(uuid4()))

    assert ingest.calls == []
    assert broker.dead_letters == []
    assert broker.acked == ["1-0"]


async def test_an_item_whose_stream_is_gone_is_dropped():
    broker, source = _Broker(), _source()
    ingest = _Ingest(fail=StreamNotFoundError(source.stream_id))
    await _consumer(broker, source, ingest).handle(_message(source.id))

    assert broker.dead_letters == []
    assert broker.acked == ["1-0"]


@pytest.mark.parametrize(
    "fields",
    [
        {"kind": "item", "item": "{}", "received_at": "2026-10-15T10:00:00Z"},
        {"source_id": "x", "kind": "item", "item": "{}", "received_at": "2026-10-15T10:00:00Z"},
        {
            "source_id": str(uuid4()),
            "kind": "?",
            "item": "{}",
            "received_at": "2026-10-15T10:00:00Z",
        },
        {
            "source_id": str(uuid4()),
            "kind": "item",
            "item": "{",
            "received_at": "2026-10-15T10:00:00Z",
        },
        {
            "source_id": str(uuid4()),
            "kind": "item",
            "item": "{}",
            "received_at": "2026-10-15T10:00:00",
        },
        {
            "source_id": str(uuid4()),
            "kind": "gap",
            "item": "{}",
            "received_at": "2026-10-15T10:00:00Z",
        },
    ],
)
def test_malformed_messages_are_refused(fields):
    with pytest.raises(MalformedItemError):
        parse_message(fields)


async def test_a_malformed_message_is_dead_lettered_not_retried():
    broker, ingest = _Broker(), _Ingest()
    message = BrokerMessage(id="1-0", fields={"kind": "item"}, delivery_count=1)
    await _consumer(broker, None, ingest).handle(message)

    assert "malformed" in broker.dead_letters[0][1]["fatal_reason"]
    assert broker.acked == ["1-0"]


async def test_start_joins_the_ingest_group_from_the_beginning():
    broker = _Broker()
    consumer = _consumer(broker, None, _Ingest())
    consumer._run = _never  # type: ignore[method-assign]
    await consumer.start()
    await consumer.stop()

    assert broker.groups == [("streams.ingest", "ingest")]


async def _never() -> None:
    return None
