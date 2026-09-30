"""The workflow-event activity: the DB row first, then the live stream, and a
failure anywhere fails the activity so Temporal retries the whole batch.

Every step must be safe to repeat, because a retry replays events that already
went through: the row is keyed by the workflow's event id, the stream carries
that same id for the read side to dedup, and channel deliveries carry a dedup
key derived from it.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_execution.activities.agent import events as events_module
from agentarea_execution.activities.agent.events import make_events_activities
from agentarea_execution.models import WorkflowEventsRequest
from agentarea_triggers.channels import register_adapter

_WORKSPACE = "ws-events"
_USER = "user-events"
_OUTBOUND = "channels:outbound"


class _Session:
    def __init__(self, log: list, *, commit_error: Exception | None = None) -> None:
        self._log = log
        self._commit_error = commit_error

    async def commit(self) -> None:
        if self._commit_error is not None:
            raise self._commit_error
        self._log.append(("commit",))

    async def rollback(self) -> None:
        self._log.append(("rollback",))

    async def close(self) -> None:
        pass


class _EventService:
    def __init__(self, log: list, *, error: Exception | None = None) -> None:
        self._log = log
        self._error = error
        self.calls: list[dict] = []

    async def create_workflow_event(self, **kwargs):
        if self._error is not None:
            raise self._error
        self.calls.append(kwargs)
        self._log.append(("db", str(kwargs["event_id"])))
        return SimpleNamespace(
            id=kwargs["event_id"],
            task_id=kwargs["task_id"],
            event_type=kwargs["event_type"],
            data=kwargs["data"],
            timestamp=kwargs["timestamp"],
        )


class _Container:
    def __init__(self, service: _EventService, session: _Session) -> None:
        self._service = service
        self._session = session

    async def get_task_event_service(self, user_context):
        return self._service, self._session


class _Broker:
    def __init__(self, log: list, *, fail_stream: bool = False) -> None:
        self._log = log
        self._fail_stream = fail_stream
        self.submits: list[tuple[str, dict]] = []

    async def submit(self, stream, fields, *, maxlen=None, ttl_seconds=None):
        if self._fail_stream and stream.startswith("events:task."):
            raise ConnectionError("redis down")
        self.submits.append((stream, dict(fields)))
        self._log.append(("xadd", stream, fields.get("ce_id")))
        return f"{len(self.submits)}-0"


class _Adapter:
    def format(self, event, presentation):
        return f"{event['event_type']}:{event['event_id']}"

    async def send(self, config, message):
        raise AssertionError("delivery happens in the consumer, not the activity")


def _event(task_id: str, event_type: str = "tool.result", **data) -> dict:
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "timestamp": datetime(2026, 9, 29, 12, 0, 0, 250000, tzinfo=UTC).isoformat(),
        "data": {"task_id": task_id, **data},
    }


def _request(*events: dict) -> WorkflowEventsRequest:
    return WorkflowEventsRequest(
        events_json=[json.dumps(e) for e in events], workspace_id=_WORKSPACE, user_id=_USER
    )


def _activity(
    *,
    service: _EventService,
    session: _Session,
    broker: _Broker | None,
    channels: bool = False,
):
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=broker,
        channel_delivery_settings=SimpleNamespace(OUTBOUND_STREAM=_OUTBOUND) if channels else None,
    )
    [activity_fn] = make_events_activities(dependencies, _Container(service, session))
    return activity_fn, dependencies


async def test_event_is_stored_with_the_workflow_identity_before_it_is_streamed():
    log: list = []
    service, broker = _EventService(log), _Broker(log)
    publish, _ = _activity(service=service, session=_Session(log), broker=broker)
    task_id = str(uuid4())
    event = _event(task_id)

    await publish(_request(event))

    [call] = service.calls
    assert call["event_id"] == UUID(event["event_id"])
    assert call["timestamp"] == datetime.fromisoformat(event["timestamp"])
    assert log == [
        ("db", event["event_id"]),
        ("commit",),
        ("xadd", f"events:task.{task_id}", event["event_id"]),
    ]
    streamed = decode(broker.submits[0][1])
    assert streamed.time == datetime.fromisoformat(event["timestamp"])


async def test_stream_failure_fails_the_activity_after_the_row_is_committed():
    log: list = []
    publish, _ = _activity(
        service=_EventService(log), session=_Session(log), broker=_Broker(log, fail_stream=True)
    )
    event = _event(str(uuid4()))

    with pytest.raises(ConnectionError, match="redis down"):
        await publish(_request(event))

    assert log == [("db", event["event_id"]), ("commit",)]


async def test_storage_failure_fails_the_activity_and_streams_nothing():
    log: list = []
    broker = _Broker(log)
    publish, _ = _activity(
        service=_EventService(log, error=RuntimeError("db down")),
        session=_Session(log),
        broker=broker,
    )

    with pytest.raises(RuntimeError, match="db down"):
        await publish(_request(_event(str(uuid4()))))

    assert broker.submits == []


async def test_commit_failure_fails_the_activity_and_streams_nothing():
    log: list = []
    broker = _Broker(log)
    publish, _ = _activity(
        service=_EventService(log),
        session=_Session(log, commit_error=ConnectionError("connection reset")),
        broker=broker,
    )

    with pytest.raises(ConnectionError, match="connection reset"):
        await publish(_request(_event(str(uuid4()))))

    assert broker.submits == []


async def test_workflow_events_are_not_published_to_pubsub():
    log: list = []
    publish, dependencies = _activity(
        service=_EventService(log), session=_Session(log), broker=_Broker(log)
    )

    await publish(_request(_event(str(uuid4()))))

    dependencies.event_broker.publish.assert_not_awaited()


async def test_a_retried_batch_repeats_channel_deliveries_under_the_same_dedup_keys(monkeypatch):
    monkeypatch.setattr(events_module, "load_task_parameters", AsyncMock(return_value={}))
    register_adapter("events-activity-test", _Adapter())
    task_id = str(uuid4())
    origin = {"type": "events-activity-test", "presentation": "verbose"}
    batch = _request(
        _event(task_id, "task.completed", channel_origin=origin, result="done"),
        _event(task_id, "task.failed", channel_origin=origin, error="boom"),
    )

    def _channel_activity():
        log: list = []
        broker = _Broker(log)
        publish, _ = _activity(
            service=_EventService(log), session=_Session(log), broker=broker, channels=True
        )
        return broker, publish

    first_broker, first = _channel_activity()
    await first(batch)
    retry_broker, retry = _channel_activity()
    await retry(batch)

    def keys(broker: _Broker) -> list[str]:
        return [fields["dedup_key"] for stream, fields in broker.submits if stream == _OUTBOUND]

    assert len(keys(first_broker)) == 2
    assert keys(first_broker) == keys(retry_broker)
    events = [json.loads(e) for e in batch.events_json]
    assert [key.rsplit(":", 1)[-1] for key in keys(first_broker)] == [e["event_id"] for e in events]


async def test_an_outbound_stream_failure_fails_the_activity(monkeypatch):
    monkeypatch.setattr(events_module, "load_task_parameters", AsyncMock(return_value={}))
    register_adapter("events-activity-test", _Adapter())
    log: list = []
    broker = _Broker(log)
    publish, _ = _activity(
        service=_EventService(log), session=_Session(log), broker=broker, channels=True
    )
    origin = {"type": "events-activity-test", "presentation": "verbose"}
    submit = broker.submit

    async def failing_outbound(stream, fields, **kwargs):
        if stream == _OUTBOUND:
            raise ConnectionError("outbound stream down")
        return await submit(stream, fields, **kwargs)

    broker.submit = failing_outbound

    with pytest.raises(ConnectionError, match="outbound stream down"):
        await publish(_request(_event(str(uuid4()), "task.completed", channel_origin=origin)))
