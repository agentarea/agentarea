"""The task SSE stream is resumable.

The feed stops after 30 minutes and the browser's EventSource reconnects,
sending the last ``id:`` it received as ``Last-Event-ID``. Every durable event
carries its stored id so that reconnect resumes after it instead of replaying
the task's whole history. Chunks are stream-only, have no stored row to resume
from, and so carry no id.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_api.api.deps.services import get_read_task_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.events.task_stream import TaskEventEnvelope
from agentarea_tasks.domain.models import AgentTask
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
