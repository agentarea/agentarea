"""The task event feed must never read events by task id alone.

Event payloads carry message content and tool arguments. The durable catch-up
reads go through ``TaskEventRepository`` under the caller's workspace; without
that filter the feed returns another tenant's history to any caller that knows
a task UUID.
"""

from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import task_event_feed
from agentarea_common.auth.context import UserContext


class _CapturingResult:
    def scalars(self) -> _CapturingResult:
        return self

    @staticmethod
    def all() -> list:
        return []

    @staticmethod
    def scalar_one_or_none() -> None:
        return None


class _CapturingSession:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, statement, params=None):
        self.statements.append(statement.compile())
        return _CapturingResult()


class _SessionContext:
    def __init__(self, session: _CapturingSession) -> None:
        self._session = session

    async def __aenter__(self) -> _CapturingSession:
        return self._session

    async def __aexit__(self, *exc_info) -> bool:
        return False


async def test_catch_up_reads_are_confined_to_the_callers_workspace(monkeypatch):
    session = _CapturingSession()
    monkeypatch.setattr(
        "agentarea_api.api.deps.database.get_db_session",
        lambda: _SessionContext(session),
    )
    reader = UserContext(user_id="reader", workspace_id="ws-1")
    task_id = str(uuid4())

    [event async for event in task_event_feed._iter_snapshot(task_id, reader)]
    await task_event_feed._load_cursor(task_id, reader, "00000000-0000-0000-0000-000000000001")

    assert len(session.statements) == 2
    for compiled in session.statements:
        assert "task_events.workspace_id" in str(compiled)
        assert "ws-1" in compiled.params.values()


@pytest.mark.parametrize("reader", ["_iter_snapshot", "_load_cursor"])
async def test_snapshot_requires_a_user_context_at_the_call_site(reader):
    """``user_context`` is positional, so the workspace cannot be forgotten by omission."""
    signature = inspect.signature(getattr(task_event_feed, reader))
    assert signature.parameters["user_context"].default is inspect.Parameter.empty


def test_a_feed_reader_cannot_be_built_without_a_workspace():
    with pytest.raises(ValueError, match="workspace_id is required"):
        UserContext(user_id="reader", workspace_id="")
