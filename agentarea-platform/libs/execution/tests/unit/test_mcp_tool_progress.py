"""A tool activity hands an MCP call its context and relays the server's progress.

Progress becomes ``tool.progress`` task events (stored, then streamed), at most
two a second per call; the call's ``structuredContent`` comes back on the result.
"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_execution.activities import agent_execution_activities as activities
from agentarea_execution.activities.agent import tools as tool_activities
from agentarea_execution.activities.agent.tool_progress import make_tool_progress_relay
from agentarea_execution.models import MCPToolRequest, McpToolRoute
from agentarea_execution.workflows.agent.tools import structured_content_field
from temporalio.testing import ActivityEnvironment


class FakeTaskEvents:
    def __init__(self) -> None:
        self.stored: list[dict[str, Any]] = []

    async def create_workflow_event(self, **fields: Any) -> None:
        self.stored.append(fields)


@pytest.fixture
def harness(monkeypatch):
    from agentarea_execution.activities import dependencies

    events = FakeTaskEvents()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=ctx)
    ctx.__aexit__ = AsyncMock(return_value=False)
    ctx.get_task_event_service = AsyncMock(return_value=events)
    ctx.get_mcp_server_instance_service = AsyncMock()
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", MagicMock())
    monkeypatch.setattr(dependencies, "ActivityContext", MagicMock(return_value=ctx))

    async def offload(**kwargs: Any) -> str:
        return kwargs["content"]

    monkeypatch.setattr(tool_activities, "_offload_large_activity_output", offload)
    broker = MagicMock(submit=AsyncMock())
    deps = MagicMock(broker_client=broker)
    fns = {fn.__name__: fn for fn in activities.make_agent_activities(deps)}
    return SimpleNamespace(
        ctx=ctx, events=events, broker=broker, activity=fns["execute_mcp_tool_activity"]
    )


@pytest.mark.asyncio
async def test_activity_passes_context_and_relays_progress(harness):
    instance = SimpleNamespace(
        id=uuid4(), name="App tools", json_spec=None, server_spec_id="spec", managed_by=None
    )
    seen: dict[str, Any] = {}

    async def execute_tool(instance_id, raw_name, tool_args, httpx_client_factory, **options):
        seen.update(options)
        for step in (1, 2, 3):
            await options["progress_callback"](step, 3, f"step {step}")
        return {
            "success": True,
            "result": "done",
            "structured_content": {"rows": 3},
            "structured_content_dropped": False,
        }

    mcp_service = harness.ctx.get_mcp_server_instance_service.return_value
    mcp_service.get = AsyncMock(return_value=instance)
    mcp_service.mcp_server_repository.get_server_by_id = AsyncMock(return_value=None)
    mcp_service.execute_tool = execute_tool
    task_id = str(uuid4())
    request = MCPToolRequest(
        tool_name="app__import_sheet",
        tool_args={},
        workspace_id="ws-1",
        user_id="user-1",
        user_context_data={"user_id": "user-1", "workspace_id": "ws-1"},
        task_id=task_id,
        tool_call_id="call-1",
        agent_id=uuid4(),
        metadata={"created_via": "api", "end_user_id": "eu-1", "app_metadata": {"chatId": "c"}},
        mcp_route=McpToolRoute(
            instance_id=str(instance.id), raw_name="import_sheet", attachment_ref=str(instance.id)
        ),
        tools=[{"type": "mcp", "name": str(instance.id)}],
    )

    result = await ActivityEnvironment().run(harness.activity, request)

    assert result.success is True
    assert result.structured_content == {"rows": 3}
    context = seen["call_context"]
    assert (context.task_id, context.tool_call_id, context.workspace_id) == (
        task_id,
        "call-1",
        "ws-1",
    )
    assert context.end_user_id == "eu-1"
    assert context.metadata == {"chatId": "c"}

    # Three notifications inside one window: the first and the finishing one.
    assert [e["event_type"] for e in harness.events.stored] == ["tool.progress"] * 2
    assert [e["data"]["progress"] for e in harness.events.stored] == [1, 3]
    first = harness.events.stored[0]
    assert first["data"] == {
        "task_id": task_id,
        "tool_name": "app__import_sheet",
        "tool_call_id": "call-1",
        "progress": 1,
        "total": 3,
        "message": "step 1",
    }
    assert first["workspace_id"] == "ws-1"
    assert harness.broker.submit.await_count == 2


@pytest.mark.asyncio
async def test_relay_throttles_heartbeats_and_survives_a_failed_write():
    now = [0.0]
    recorded: list[dict[str, Any]] = []
    beats: list[int] = []

    async def record(data: dict[str, Any]) -> None:
        if data["message"] == "boom":
            raise RuntimeError("db down")
        recorded.append(data)

    relay = make_tool_progress_relay(
        record=record,
        task_id="t",
        tool_name="tool",
        tool_call_id="c",
        heartbeat=lambda: beats.append(1),
        clock=lambda: now[0],
    )

    await relay(1, None, "a")
    now[0] = 0.2
    await relay(2, None, "b")  # inside the window: dropped
    now[0] = 0.6
    await relay(3, None, "boom")  # recorded attempt fails, call goes on
    now[0] = 1.2
    await relay(4, None, None)

    assert [d["progress"] for d in recorded] == [1, 4]
    assert len(beats) == 4


def test_tool_result_carries_structured_content_only_when_present():
    assert structured_content_field({"structured_content": {"a": 1}}) == {
        "structured_content": {"a": 1}
    }
    assert structured_content_field({"structured_content_dropped": True}) == {
        "structured_content_dropped": True
    }
    assert structured_content_field({"result": "text"}) == {}
