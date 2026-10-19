"""The workflow-event activity of runs from before the task log: the DB row first,
then ``tasks.events``, and a failure anywhere fails the activity so Temporal
retries the whole batch.

Every step must be safe to repeat, because a retry replays events that already
went through: the row is keyed by the workflow's event id and the topic carries
that same id for readers to dedup. Who gets each event is the delivery group's
business, not the activity's.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_common.events.adapters.redis_streams import decode
from agentarea_execution.activities.agent.events import make_events_activities
from agentarea_execution.models import WorkflowEventsRequest

_WORKSPACE = "ws-events"
_USER = "user-events"


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


class _Audit:
    """Audit trail keyed by event id, as the real insert-once table is."""

    def __init__(self) -> None:
        self.rows: dict[UUID, dict] = {}

    async def record_once(self, event_id, action, resource_type, resource_id=None, **fields):
        if event_id in self.rows:
            return False
        self.rows[event_id] = {
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            **fields,
        }
        return True


class _Container:
    def __init__(self, service: _EventService, session: _Session, audit: _Audit) -> None:
        self._service = service
        self._session = session
        self._audit = audit

    async def get_task_event_service(self, user_context):
        return self._service, self._session

    async def get_audit_service(self, user_context):
        return self._audit, self._session


class _Broker:
    def __init__(self, log: list, *, fail_stream: bool = False) -> None:
        self._log = log
        self._fail_stream = fail_stream
        self.submits: list[tuple[str, dict]] = []

    async def submit(self, stream, fields, *, retention):
        if self._fail_stream and stream == "tasks.events":
            raise ConnectionError("redis down")
        self.submits.append((stream, dict(fields)))
        self._log.append(("xadd", stream, fields.get("ce_id")))
        return f"{len(self.submits)}-0"

    async def notify(self, channel, fields):
        self._log.append(("notify", channel, fields.get("ce_id")))


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
    audit: _Audit | None = None,
):
    dependencies = SimpleNamespace(
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=broker,
    )
    [activity_fn] = make_events_activities(
        dependencies, _Container(service, session, audit or _Audit())
    )
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
        ("xadd", "tasks.events", event["event_id"]),
    ]
    streamed = decode(broker.submits[0][1])
    assert streamed.time == datetime.fromisoformat(event["timestamp"])
    assert (streamed.subject, streamed.extensions["workspace"]) == (task_id, _WORKSPACE)


async def test_a_live_only_signal_is_broadcast_not_put_on_tasks_events():
    log: list = []
    broker = _Broker(log)
    publish, _ = _activity(service=_EventService(log), session=_Session(log), broker=broker)
    task_id = str(uuid4())
    started = _event(task_id, "llm.call.started")

    await publish(_request(started))

    assert broker.submits == []
    assert log[-1] == ("notify", f"tasks.live.{task_id}", started["event_id"])


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


def _tool_event(task_id: str, agent_id: str, event_type: str, **data) -> dict:
    return _event(task_id, event_type, agent_id=agent_id, tool_call_id="call-1", **data)


async def test_tool_call_outcomes_reach_the_audit_trail_without_argument_values():
    log: list = []
    audit = _Audit()
    publish, _ = _activity(
        service=_EventService(log), session=_Session(log), broker=_Broker(log), audit=audit
    )
    task_id, agent_id = str(uuid4()), str(uuid4())
    allowed = _tool_event(
        task_id, agent_id, "tool.call", tool_name="shell", arguments={"token": "sk-secret"}
    )
    denied = _tool_event(
        task_id,
        agent_id,
        "tool.result",
        tool_name="rm",
        success=False,
        denied_by_policy=True,
        error="Tool call denied by policy: not permitted by policy",
    )
    gated = _tool_event(
        task_id,
        agent_id,
        "approval.requested",
        tool_name="deploy",
        escalation_id="esc-1",
        arguments={"env": "prod"},
        message="Tool 'deploy' requires human approval",
    )
    decided = _tool_event(
        task_id,
        agent_id,
        "approval.decided",
        tool_name="deploy",
        escalation_id="esc-1",
        approved=False,
        approved_by="approver-1",
        comment="not today",
    )
    ran = _tool_event(task_id, agent_id, "tool.result", tool_name="shell", success=True)

    await publish(_request(allowed, denied, gated, decided, ran))

    rows = {str(event_id): row for event_id, row in audit.rows.items()}
    assert {event_id: row["action"] for event_id, row in rows.items()} == {
        allowed["event_id"]: "tool.call.allowed",
        denied["event_id"]: "tool.call.denied",
        gated["event_id"]: "tool.call.approval_required",
        decided["event_id"]: "approval.denied",
    }
    for event_id in (allowed["event_id"], denied["event_id"], gated["event_id"]):
        row = rows[event_id]
        assert (row["actor_type"], row["actor_id"]) == ("agent", agent_id)
        assert (row["resource_type"], row["resource_id"]) == ("task", task_id)
        assert row["event_metadata"]["requested_by"] == _USER
    assert rows[allowed["event_id"]]["event_metadata"]["argument_keys"] == ["token"]
    assert "sk-secret" not in json.dumps(list(rows.values()))
    assert rows[denied["event_id"]]["event_metadata"]["reason"].endswith("not permitted by policy")
    decision = rows[decided["event_id"]]
    assert (decision["actor_type"], decision["actor_id"]) == ("user", "approver-1")
    assert decision["event_metadata"]["decision"] == "denied"
    assert decision["event_metadata"]["comment"] == "not today"


async def test_a_retried_batch_does_not_audit_a_tool_call_twice():
    audit = _Audit()
    task_id, agent_id = str(uuid4()), str(uuid4())
    batch = _request(_tool_event(task_id, agent_id, "tool.call", tool_name="shell"))

    for _ in range(2):
        log: list = []
        publish, _ = _activity(
            service=_EventService(log), session=_Session(log), broker=_Broker(log), audit=audit
        )
        await publish(batch)

    assert [row["action"] for row in audit.rows.values()] == ["tool.call.allowed"]


async def test_a_decision_less_approval_response_is_not_a_second_decision():
    """Pre-patch denials emitted a second approval.decided carrying no decision."""
    log: list = []
    audit = _Audit()
    publish, _ = _activity(
        service=_EventService(log), session=_Session(log), broker=_Broker(log), audit=audit
    )

    await publish(
        _request(
            _tool_event(
                str(uuid4()), str(uuid4()), "approval.decided", tool_name="x", comment="no"
            )
        )
    )

    assert audit.rows == {}
