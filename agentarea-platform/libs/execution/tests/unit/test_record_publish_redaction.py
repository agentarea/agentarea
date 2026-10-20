"""The record activity publishes a tool call's arguments and result as the event log redacts them."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from agentarea_common.events.adapters.redis_streams import decode
from agentarea_execution.activities.agent import record
from agentarea_execution.activities.agent.record import make_record_activities
from agentarea_execution.models import LogRow, RecordRequest

BEARER = "sk-live-4f9a2c"
PASSWORD = "hunter2-correct-horse"  # pragma: allowlist secret


class _Log:
    def __init__(self, *_args):
        pass

    async def append(self, *_args, **_kwargs):
        return None


class _Broker:
    def __init__(self) -> None:
        self.published: list[dict] = []

    async def submit(self, stream, fields, *, retention):
        event = decode(fields)
        self.published.append({"type": event.type, "data": event.data})
        return "1-0"

    async def notify(self, channel, fields):
        raise AssertionError("no live-only signal here")


def _session():
    return SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), close=AsyncMock())


async def test_a_secret_in_tool_arguments_is_never_published(monkeypatch):
    monkeypatch.setattr(record, "TaskLog", _Log)
    monkeypatch.setattr(record, "store_task_events", AsyncMock())
    arguments = {
        "command": f"curl -H 'Authorization: Bearer {BEARER}' https://api.example.com",
        "password": PASSWORD,
    }
    redacted = {"command": "[omitted]", "password": "[redacted]"}
    workspace_id = str(uuid4())
    request = RecordRequest(
        task_id=str(uuid4()),
        workspace_id=workspace_id,
        user_id="writer",
        execution_id="exec-1",
        rows=[
            LogRow(
                seq=1,
                event_id=str(uuid4()),
                role="assistant",
                tool_calls=[
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "shell", "arguments": json.dumps(arguments)},
                    }
                ],
            ),
            LogRow(
                seq=2,
                event_id=str(uuid4()),
                role="tool",
                content=f"token={BEARER} ok",
                tool_call_id="call-1",
            ),
            *(
                LogRow(
                    seq=3 + offset,
                    event_id=str(uuid4()),
                    kind="event",
                    role="event",
                    name=name,
                    meta={"tool_call_id": "call-1", "tool_name": "shell", "arguments": redacted},
                )
                for offset, name in enumerate(("tool.call", "tool.result"))
            ),
        ],
    )
    broker = _Broker()
    container = SimpleNamespace(
        _database=SimpleNamespace(async_session_factory=_session),
        log_body_store=lambda: None,
    )
    [record_activity] = make_record_activities(SimpleNamespace(broker_client=broker), container)

    await record_activity(request)

    assert [event["type"] for event in broker.published] == ["tool.call", "tool.result"]
    for event in broker.published:
        assert BEARER not in json.dumps(event["data"])
        assert PASSWORD not in json.dumps(event["data"])
        assert event["data"]["arguments"]["password"] == "[redacted]"
