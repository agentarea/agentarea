"""An agent reads a stream from its own cursor: what arrived since its last run."""

import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents_sdk.tools.code_tools_loader import (
    get_code_tool_class,
    get_code_tools_metadata,
)
from agentarea_api.tools.stream_events_toolset import StreamEventsToolset
from agentarea_streams.domain import JournaledEvent, StreamNotFoundError
from agentarea_triggers.event_context import UNTRUSTED_DATA_NOTICE
from fastapi import HTTPException

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
MODULE = "agentarea_api.tools.stream_events_toolset"


def _event(sequence: int, **data) -> JournaledEvent:
    return JournaledEvent(
        type="payment.succeeded",
        source="webhook:yookassa",
        data=data or {"n": sequence},
        stream_id=uuid4(),
        sequence=sequence,
        event_key=f"k{sequence}",
        received_at=NOW,
        time=NOW,
    )


@pytest.fixture
def env(monkeypatch):
    stream = SimpleNamespace(id=uuid4(), name="payments")
    service = AsyncMock()
    service.find_stream.return_value = stream
    permission = AsyncMock()

    @asynccontextmanager
    async def ctx():
        yield (None, SimpleNamespace(user_id="u", workspace_id="w"), object(), None, None)

    monkeypatch.setattr(f"{MODULE}.platform_read_context", ctx)
    monkeypatch.setattr(f"{MODULE}._service", lambda _f: service)
    monkeypatch.setattr(f"{MODULE}.require_permission", permission)
    return SimpleNamespace(stream=stream, service=service, permission=permission)


async def _read(**kwargs) -> dict:
    return json.loads(await StreamEventsToolset().read_stream(**kwargs))


def test_the_worker_can_build_it_and_the_catalog_files_it_under_operate():
    assert get_code_tool_class("agentarea/stream_events") is StreamEventsToolset
    entry = get_code_tools_metadata()["agentarea/stream_events"]
    assert entry["plane"] == "operate"
    assert [m["name"] for m in entry["available_methods"]] == ["read_stream"]
    assert entry["available_methods"][0]["effect"] == "read"


async def test_events_after_the_cursor_come_with_the_next_cursor(env):
    env.service.list_events.return_value = [_event(41), _event(42), _event(43)]
    page = await _read(stream="payments", after_sequence=40, limit=2)
    env.service.find_stream.assert_awaited_once_with("payments")
    env.permission.assert_awaited_once_with("read", "stream", str(env.stream.id), "u")
    assert env.service.list_events.await_args.kwargs == {"after": 40, "before": None, "limit": 3}
    assert page["stream"] == {"id": str(env.stream.id), "name": "payments"}
    assert [e["sequence"] for e in page["events"]] == [41, 42]
    first = page["events"][0]
    assert first["kind"] == "payment.succeeded"
    assert first["key"] == "k41"
    assert first["occurred_at"].startswith("2026-10-06T12:00:00")
    assert first["data"] == {"n": 41}
    assert page["next_after"] == 42
    assert page["has_more"] is True
    assert page["untrusted"] == UNTRUSTED_DATA_NOTICE


async def test_a_page_that_ends_the_stream_says_nothing_more_is_waiting(env):
    env.service.list_events.return_value = [_event(41), _event(42)]
    page = await _read(stream="payments", after_sequence=40, limit=2)
    assert [e["sequence"] for e in page["events"]] == [41, 42]
    assert page["next_after"] == 42
    assert page["has_more"] is False


async def test_nothing_new_keeps_the_cursor_where_it_was(env):
    env.service.list_events.return_value = []
    page = await _read(stream=str(env.stream.id), after_sequence=99)
    assert page["events"] == []
    assert page["next_after"] == 99
    assert page["has_more"] is False


async def test_credentials_in_an_event_never_reach_the_agent(env):
    env.service.list_events.return_value = [
        _event(1, headers={"Authorization": "Bearer x", "X-Event": "e"}, text="hi")
    ]
    page = await _read(stream="payments")
    assert page["events"][0]["data"] == {"headers": {"X-Event": "e"}, "text": "hi"}


async def test_a_stream_the_caller_may_not_read_is_refused_before_reading(env):
    env.permission.side_effect = HTTPException(status_code=403, detail="Permission denied")
    page = await _read(stream="payments")
    assert page == {"error": "Permission denied"}
    env.service.list_events.assert_not_called()


async def test_an_unknown_stream_is_an_error_not_an_empty_page(env):
    env.service.find_stream.side_effect = StreamNotFoundError("nope")
    assert "not found" in (await _read(stream="nope"))["error"]


@pytest.mark.parametrize(("kwargs", "says"), [({"limit": 0}, "limit"), ({"limit": 201}, "limit"), ({"after_sequence": -1}, "after_sequence")])
async def test_bounds_match_the_rest_events_list(env, kwargs, says):
    page = await _read(stream="payments", **kwargs)
    assert says in page["error"]
    env.service.find_stream.assert_not_called()
