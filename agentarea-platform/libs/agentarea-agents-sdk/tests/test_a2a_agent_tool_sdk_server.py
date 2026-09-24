"""A2AAgentTool delegates to an agent served by the official A2A SDK.

The remote side is the SDK's own reference server (``DefaultRequestHandler``,
in-memory task store, JSON-RPC routes) with a trivial echo executor, reached
in-process through ``httpx.ASGITransport``. If the tool can read the answer
from that server, it can read it from any conforming A2A agent.
"""

import asyncio

import httpx
import pytest
from a2a.helpers.proto_helpers import new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    Task,
    TaskState,
    TaskStatus,
)
from starlette.applications import Starlette

from agentarea_agents_sdk.tools import a2a_agent_tool
from agentarea_agents_sdk.tools.a2a_agent_tool import A2AAgentTool

RPC_URL = "http://specialist.test/a2a"


class EchoExecutor(AgentExecutor):
    """Answers every message with ``echo: <text>`` after a short think."""

    def __init__(self) -> None:
        self.seen_authorization: list[str | None] = []

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        headers = context.call_context.state.get("headers", {})
        self.seen_authorization.append(headers.get("authorization"))
        await event_queue.enqueue_event(
            Task(
                id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
            )
        )
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()
        await asyncio.sleep(0.05)
        await updater.add_artifact([new_text_part(f"echo: {context.get_user_input()}")])
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


@pytest.fixture
def executor() -> EchoExecutor:
    return EchoExecutor()


@pytest.fixture
def sdk_server(executor) -> httpx.ASGITransport:
    card = AgentCard(
        name="specialist",
        description="Echoes what it is told.",
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(url=RPC_URL, protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
    )
    handler = DefaultRequestHandler(
        agent_executor=executor, task_store=InMemoryTaskStore(), agent_card=card
    )
    app = Starlette(routes=create_jsonrpc_routes(handler, rpc_url="/a2a"))
    return httpx.ASGITransport(app=app)


@pytest.mark.asyncio
async def test_tool_reads_the_answer_from_an_sdk_served_agent(sdk_server, executor, monkeypatch):
    monkeypatch.setattr(a2a_agent_tool, "_POLL_INTERVAL", 0.02)
    tool = A2AAgentTool(
        agent_name="specialist",
        agent_description="Echoes.",
        a2a_url=RPC_URL,
        auth_token="coordinator-key",
        http_transport=sdk_server,
    )

    result = await tool.execute(message="revenue is up 12%")

    assert result["success"] is True
    assert result["result"] == "echo: revenue is up 12%"
    assert result["task_state"] == "TASK_STATE_COMPLETED"
    assert result["task_id"]
    assert executor.seen_authorization == ["Bearer coordinator-key"]
