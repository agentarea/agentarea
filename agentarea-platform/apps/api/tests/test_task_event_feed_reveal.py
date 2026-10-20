"""The SSE feed shows a tool call to each caller as REST does: replayed and live alike.

The task's authority (its starter or a workspace admin) sees the command and the
output whole with their secrets masked; any other member sees them as the event
log redacts them. The broker's copy, which every feed tails, stays redacted.
"""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import task_event_feed
from agentarea_api.api.v1.task_event_feed import feed_envelope, open_task_event_feed
from agentarea_common.auth.context import UserContext
from agentarea_common.events.task_stream import TaskEventEnvelope

from .test_task_event_stream_resume import AGENT_ID, TASK_ID, async_client, feed_calls  # noqa: F401
from .tool_call_log import EVENT_ROWS, FakeFeedReader, assert_member_view, assert_owner_view

COMPLETED = TaskEventEnvelope("task.completed", str(uuid4()), None, {"message": "done"}, seq=5)


class _Reader(FakeFeedReader):
    snapshot: list = []

    async def after(self, task_id, *, after_seq, limit):
        return [row for row in self.snapshot if row.seq > after_seq][:limit]


class _Hub:
    def __init__(self, live: list[TaskEventEnvelope]):
        self.live = live

    @asynccontextmanager
    async def subscribe(self, task_id):
        queue: asyncio.Queue = asyncio.Queue()
        for env in self.live:
            queue.put_nowait(env)
        yield queue


@asynccontextmanager
async def _session():
    yield None


async def _feed(monkeypatch, *, snapshot, live, revealed):
    _Reader.snapshot = snapshot
    monkeypatch.setattr(task_event_feed, "TaskFeedReader", _Reader)
    monkeypatch.setattr("agentarea_api.api.deps.database.get_db_session", _session)
    monkeypatch.setattr(task_event_feed, "task_events_hub", lambda: _Hub(live))
    shown = [
        env
        async for env in open_task_event_feed(
            uuid4(),
            user_context=UserContext(user_id="u", workspace_id="w"),
            terminal_types=frozenset({"task.completed"}),
            revealed=revealed,
        )
    ]
    call, result = (env.data for env in shown if env.event_type.startswith("tool."))
    return call, result


@pytest.mark.parametrize("revealed", [True, False])
async def test_a_replayed_tool_call_is_shown_as_the_caller_may_see_it(monkeypatch, revealed):
    call, result = await _feed(monkeypatch, snapshot=EVENT_ROWS, live=[COMPLETED], revealed=revealed)
    (assert_owner_view if revealed else assert_member_view)(call, result)


@pytest.mark.parametrize("revealed", [True, False])
async def test_a_live_tool_call_is_shown_as_the_caller_may_see_it(monkeypatch, revealed):
    from_broker = [feed_envelope(row) for row in EVENT_ROWS]
    assert all(env is not None for env in from_broker)
    call, result = await _feed(
        monkeypatch, snapshot=[], live=[*from_broker, COMPLETED], revealed=revealed
    )
    (assert_owner_view if revealed else assert_member_view)(call, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("may_act", [True, False])
async def test_the_stream_decides_once_who_its_caller_is(
    async_client,  # noqa: F811
    feed_calls,  # noqa: F811
    monkeypatch,
    may_act,
):
    decide = AsyncMock(return_value=may_act)
    monkeypatch.setattr("agentarea_api.api.v1.agents_tasks.caller_may_act_on_task", decide)

    response = await async_client.get(
        f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/events/stream"
    )

    assert response.status_code == 200, response.text
    assert feed_calls[0]["revealed"] is may_act
    decide.assert_awaited_once()
