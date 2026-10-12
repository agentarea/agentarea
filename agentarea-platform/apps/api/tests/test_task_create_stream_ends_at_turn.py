"""The streaming create ends at the turn's terminal event unless asked to follow."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import agents_tasks
from agentarea_api.api.v1.agents_tasks import TaskCreate, create_task_for_agent_with_stream
from agentarea_common.auth.context import UserContext


async def _stream(monkeypatch, *, follow: bool) -> dict:
    seen: dict = {}

    async def fake_tail(*args, **kwargs):
        seen.update(kwargs)
        yield "event: task.completed\ndata: {}\n\n"

    monkeypatch.setattr(agents_tasks, "_tail_task_events_sse", fake_tail)
    agent_id = uuid4()
    task = SimpleNamespace(
        id=uuid4(),
        description="d",
        status="running",
        execution_id="e-1",
        created_at=datetime.now(UTC),
        result=None,
    )
    task_service = SimpleNamespace(start_run=AsyncMock(return_value=task))
    agent_service = SimpleNamespace(
        get_with_catalog=AsyncMock(return_value=SimpleNamespace(name="A"))
    )

    response = await create_task_for_agent_with_stream(
        agent_id=agent_id,
        data=TaskCreate(description="d"),
        user_context=UserContext(user_id="u", workspace_id="w", api_key_id="k"),
        secret_manager=SimpleNamespace(),
        follow=follow,
        task_service=task_service,  # type: ignore[arg-type]
        agent_service=agent_service,  # type: ignore[arg-type]
    )
    async for _ in response.body_iterator:
        pass
    return seen


@pytest.mark.asyncio
async def test_by_default_the_create_stream_does_not_wait_for_follow_ups(monkeypatch):
    assert (await _stream(monkeypatch, follow=False))["follow_execution"] is False


@pytest.mark.asyncio
async def test_follow_keeps_the_create_stream_through_the_follow_up_window(monkeypatch):
    assert (await _stream(monkeypatch, follow=True))["follow_execution"] is True
