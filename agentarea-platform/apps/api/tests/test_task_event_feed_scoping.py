"""The task event feed must never read events by task id alone.

Event payloads carry message content and tool arguments. The durable catch-up
read is hand-written SQL rather than a call through ``TaskEventRepository``, so
nothing but these tests keeps its workspace filter in place; without it the feed
returns another tenant's history to any caller that knows a task UUID.
"""

from __future__ import annotations

import inspect

import pytest
from agentarea_api.api.v1 import task_event_feed


class _CapturingResult:
    @staticmethod
    def fetchall() -> list:
        return []

    @staticmethod
    def first() -> None:
        return None


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list[tuple[str, dict]] = []

    async def execute(self, statement, params):
        self.statements.append((str(statement), params))
        return _CapturingResult()


class _SessionContext:
    def __init__(self, session: _CapturingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _CapturingSession:
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


async def test_snapshot_query_filters_on_workspace(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(
        "agentarea_api.api.deps.database.get_db_session",
        lambda: _SessionContext(session),
    )

    [event async for event in task_event_feed._iter_snapshot("task-1", "ws-1")]
    await task_event_feed._load_cursor("task-1", "ws-1", "00000000-0000-0000-0000-000000000001")

    for sql, params in session.statements:
        assert "workspace_id = :workspace_id" in sql
        assert params["task_id"] == "task-1"
        assert params["workspace_id"] == "ws-1"
    assert len(session.statements) == 2


@pytest.mark.parametrize("reader", ["_iter_snapshot", "_load_cursor"])
async def test_snapshot_requires_a_workspace_at_the_call_site(reader):
    """``workspace_id`` is positional, so it cannot be forgotten by omission."""
    signature = inspect.signature(getattr(task_event_feed, reader))
    workspace_param = signature.parameters["workspace_id"]
    assert workspace_param.default is inspect.Parameter.empty


async def test_feed_refuses_a_blank_workspace():
    feed = task_event_feed.open_task_event_feed(
        "task-1",
        workspace_id="",
        terminal_types=frozenset(),
    )
    with pytest.raises(ValueError, match="workspace_id is required"):
        await anext(feed)
