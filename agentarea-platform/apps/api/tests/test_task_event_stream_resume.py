"""The task SSE stream is resumable.

The feed stops after 30 minutes and the browser's EventSource reconnects,
sending the last ``id:`` it received as ``Last-Event-ID``. Every durable event
carries its stored id so that reconnect resumes after it instead of replaying
the task's whole history. Chunks are stream-only, have no stored row to resume
from, and so carry no id.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps import services
from agentarea_api.api.deps.services import get_read_task_service
from agentarea_api.api.v1 import agents_tasks, task_event_feed
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.config.database import get_read_db_session
from agentarea_common.events.task_stream import TaskEventEnvelope
from agentarea_tasks.domain.models import AgentTask
from agentarea_tasks.task_service import TaskService
from httpx import ASGITransport, AsyncClient

AGENT_ID = uuid4()
TASK_ID = uuid4()
DURABLE_ID = str(uuid4())


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def feed_calls(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def feed(task_id, **kwargs):
        calls.append(kwargs)
        yield TaskEventEnvelope("llm.call.chunk", str(uuid4()), None, {"chunk": "po"})
        yield TaskEventEnvelope("task.completed", DURABLE_ID, None, {"message": "done"})

    monkeypatch.setattr("agentarea_api.api.v1.task_event_feed.open_task_event_feed", feed)

    task_service = AsyncMock()
    task_service.get_task.return_value = AgentTask(
        id=TASK_ID,
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=AGENT_ID,
        status="running",
        execution_id="exec-1",
    )
    user_context = MagicMock(user_id="test_user", workspace_id="test_workspace")
    app.dependency_overrides[get_read_task_service] = lambda: task_service
    app.dependency_overrides[get_user_context] = lambda: user_context
    yield calls
    app.dependency_overrides.pop(get_read_task_service, None)
    app.dependency_overrides.pop(get_user_context, None)


def _frames(body: str) -> list[dict[str, str]]:
    frames = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        frames.append(fields)
    return frames


@pytest.mark.asyncio
async def test_durable_events_carry_their_id_and_chunks_do_not(async_client, feed_calls):
    response = await async_client.get(
        f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/events/stream"
    )

    assert response.status_code == 200, response.text
    frames = {frame["event"]: frame for frame in _frames(response.text)}
    assert frames["task.completed"]["id"] == DURABLE_ID
    assert "id" not in frames["llm.call.chunk"]
    assert "id" not in frames["connected"]
    assert feed_calls[0]["last_event_id"] is None


@pytest.mark.asyncio
async def test_a_reconnect_resumes_after_the_last_event_id(async_client, feed_calls):
    response = await async_client.get(
        f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/events/stream",
        headers={"Last-Event-ID": DURABLE_ID},
    )

    assert response.status_code == 200, response.text
    assert feed_calls[0]["last_event_id"] == DURABLE_ID


@pytest.mark.asyncio
async def test_sse_heartbeat_does_not_cancel_pending_frame():
    release = asyncio.Event()

    async def frames():
        yield "event: connected\n\n"
        await release.wait()
        yield "event: task.completed\n\n"

    stream = agents_tasks._with_sse_heartbeats(frames(), interval_seconds=0.01)
    assert await anext(stream) == "event: connected\n\n"
    assert await asyncio.wait_for(anext(stream), timeout=0.2) == ": ping\n\n"
    assert await asyncio.wait_for(anext(stream), timeout=0.2) == ": ping\n\n"

    release.set()
    assert await asyncio.wait_for(anext(stream), timeout=0.2) == "event: task.completed\n\n"
    await stream.aclose()


async def _drain(stream) -> list[str]:
    return [frame async for frame in stream]


@pytest.mark.asyncio
async def test_sse_heartbeat_keeps_a_deadline_held_across_yield():
    """The event feed bounds itself with an ``asyncio.timeout`` held across ``yield``."""

    async def frames():
        try:
            async with asyncio.timeout(0.2):
                yield "event: first\n\n"
                await asyncio.sleep(5)
                yield "event: late\n\n"
        except TimeoutError:
            return

    stream = agents_tasks._with_sse_heartbeats(frames(), interval_seconds=10)
    assert await asyncio.wait_for(_drain(stream), timeout=2) == ["event: first\n\n"]


@pytest.mark.asyncio
async def test_sse_heartbeat_ends_when_the_deadline_hits_a_slow_reader():
    """A deadline that fires while frames wait for the reader still ends the stream.

    The frame the deadline cut is dropped; a reconnect resumes from the last id.
    """

    async def frames():
        try:
            async with asyncio.timeout(0.2):
                for name in ("a", "b", "c"):
                    yield f"event: {name}\n\n"
                await asyncio.sleep(5)
        except TimeoutError:
            return

    stream = agents_tasks._with_sse_heartbeats(frames(), interval_seconds=10)
    assert await anext(stream) == "event: a\n\n"
    await asyncio.sleep(0.4)
    assert await asyncio.wait_for(_drain(stream), timeout=2) == ["event: b\n\n"]


@pytest.mark.asyncio
async def test_sse_heartbeat_propagates_a_source_failure_after_its_frames():
    async def frames():
        yield "event: connected\n\n"
        raise RuntimeError("feed broke")

    stream = agents_tasks._with_sse_heartbeats(frames(), interval_seconds=10)
    assert await anext(stream) == "event: connected\n\n"
    with pytest.raises(RuntimeError, match="feed broke"):
        await anext(stream)


@pytest.mark.asyncio
async def test_sse_heartbeat_closes_the_source_when_the_client_goes_away():
    closed = asyncio.Event()

    async def frames():
        try:
            yield "event: connected\n\n"
            await asyncio.Event().wait()
        finally:
            closed.set()

    stream = agents_tasks._with_sse_heartbeats(frames(), interval_seconds=10)
    assert await anext(stream) == "event: connected\n\n"
    reader = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.05)
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reader
    assert closed.is_set()


@pytest.mark.asyncio
async def test_event_stream_closes_read_session_before_first_frame(monkeypatch):
    session = MagicMock(closed=False)
    task = AgentTask(
        id=TASK_ID,
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=AGENT_ID,
        status="running",
        execution_id="exec-1",
    )

    async def read_session():
        try:
            yield session
        finally:
            session.closed = True

    async def get_task(self, task_id):
        return task

    async def feed(task_id, **kwargs):
        yield TaskEventEnvelope("task.completed", DURABLE_ID, None, {"message": "done"})

    monkeypatch.setitem(app.dependency_overrides, get_read_db_session, read_session)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_user_context,
        lambda: MagicMock(user_id="test_user", workspace_id="test_workspace"),
    )
    monkeypatch.setitem(app.dependency_overrides, services.get_event_broker, lambda: object())
    monkeypatch.setattr(services, "_create_task_manager", AsyncMock(return_value=object()))
    monkeypatch.setattr(services, "get_temporal_workflow_service", AsyncMock(return_value=object()))
    monkeypatch.setattr(TaskService, "get_task", get_task)
    monkeypatch.setattr(task_event_feed, "open_task_event_feed", feed)

    async def assert_session_closed_before_body(scope, receive, send):
        async def checked_send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                assert session.closed, "read DB session was open when SSE body started"
            await send(message)

        await app(scope, receive, checked_send)

    async with AsyncClient(
        transport=ASGITransport(app=assert_session_closed_before_body),
        base_url="http://test",
    ) as client:
        response = await client.get(
            f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/{TASK_ID}/events/stream"
        )

    assert response.status_code == 200, response.text
    assert "event: connected" in response.text


@pytest.mark.asyncio
async def test_task_creation_runs_before_first_sse_frame(monkeypatch):
    agent = MagicMock(name="agent")
    agent.name = "Test agent"
    agent_service = MagicMock()
    agent_service.get_with_catalog = AsyncMock(return_value=agent)
    task = AgentTask(
        id=TASK_ID,
        title="task",
        description="do the thing",
        query="do the thing",
        user_id="test_user",
        workspace_id="test_workspace",
        agent_id=AGENT_ID,
        status="failed",
        execution_id=None,
    )
    task_service = MagicMock()
    task_service.start_run = AsyncMock(return_value=task)
    monkeypatch.setitem(
        app.dependency_overrides, agents_tasks.get_agent_service, lambda: agent_service
    )
    monkeypatch.setitem(
        app.dependency_overrides, agents_tasks.get_task_service, lambda: task_service
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        get_user_context,
        lambda: MagicMock(user_id="test_user", workspace_id="test_workspace"),
    )

    async def assert_started_before_body(scope, receive, send):
        async def checked_send(message):
            if message["type"] == "http.response.body" and message.get("body"):
                assert task_service.start_run.await_count == 1
            await send(message)

        await app(scope, receive, checked_send)

    async with AsyncClient(
        transport=ASGITransport(app=assert_started_before_body),
        base_url="http://test",
    ) as client:
        response = await client.post(
            f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/",
            json={"description": "do the thing"},
        )

    assert response.status_code == 200, response.text
    assert "event: task_created" in response.text


@pytest.mark.asyncio
async def test_streamed_task_create_rejects_an_invalid_run_with_422(monkeypatch, async_client):
    """An invalid run is a request error, not an "agent not found" SSE frame."""
    agent = MagicMock(name="agent")
    agent.name = "Test agent"
    agent_service = MagicMock()
    agent_service.get_with_catalog = AsyncMock(return_value=agent)
    task_service = MagicMock()
    task_service.start_run = AsyncMock()
    monkeypatch.setitem(
        app.dependency_overrides, agents_tasks.get_agent_service, lambda: agent_service
    )
    monkeypatch.setitem(
        app.dependency_overrides, agents_tasks.get_task_service, lambda: task_service
    )
    monkeypatch.setitem(
        app.dependency_overrides,
        get_user_context,
        lambda: MagicMock(user_id="test_user", workspace_id="test_workspace"),
    )

    response = await async_client.post(
        f"/v1/workspaces/acme/agents/{AGENT_ID}/tasks/", json={"description": ""}
    )

    assert response.status_code == 422, response.text
    assert [error["loc"] for error in response.json()["errors"]] == [["description"]]
    task_service.start_run.assert_not_awaited()
