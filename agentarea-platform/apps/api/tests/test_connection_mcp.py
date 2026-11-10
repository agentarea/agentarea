"""An API connection answers MCP at the address every connection has.

An MCP client speaks to ``ConnectionMCPResponse`` over Streamable HTTP; the
connection's operations are its tools, and a call runs through the same governed
path an agent's call takes (``client_mcp.call_openapi_tool``, stubbed here).
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx2
import pytest
from agentarea_api.api.v1 import client_mcp, connection_mcp
from agentarea_api.api.v1.connection_mcp import ConnectionMCPResponse
from agentarea_common.auth.context import UserContext
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent
from starlette.applications import Starlette
from starlette.routing import Route

CONNECTION_ID = uuid4()
CALLER = UserContext(user_id="user-1", workspace_id="ws-1")


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, dict]]:
    connection = SimpleNamespace(
        id=CONNECTION_ID,
        name="Metrika",
        available_tools=[
            {
                "name": "getStatData",
                "description": "Report data",
                "inputSchema": {"type": "object", "properties": {"ids": {"type": "string"}}},
            },
            {"name": "deleteCounter", "description": "Delete a counter"},
        ],
    )

    @asynccontextmanager
    async def service(_user_ctx):
        yield object(), SimpleNamespace(get_connection=AsyncMock(return_value=connection))

    recorded: list[tuple[str, dict]] = []

    async def call_openapi_tool(_session, user_ctx, _service, _connection, operation, arguments):
        assert user_ctx is CALLER
        recorded.append((operation, arguments))
        return CallToolResult(content=[TextContent(type="text", text="42 visits")])

    monkeypatch.setattr(connection_mcp, "_connection_service", service)
    monkeypatch.setattr(client_mcp, "call_openapi_tool", call_openapi_tool)
    return recorded


def _policy(monkeypatch, policy: dict) -> None:
    monkeypatch.setattr(client_mcp, "_effective_tool_policy", AsyncMock(return_value=policy))


@asynccontextmanager
async def _session():
    connection_mcp.build_app(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app = Starlette(
        routes=[
            Route(
                "/v1/mcp/{id}/mcp",
                endpoint=lambda _request: ConnectionMCPResponse(CALLER, CONNECTION_ID),
                methods=["GET", "POST", "DELETE"],
            )
        ]
    )
    async with (
        connection_mcp.connection_mcp_server.session_manager.run(),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app=app), base_url="http://api") as http,
        streamable_http_client(f"http://api/v1/mcp/{CONNECTION_ID}/mcp", http_client=http) as (
            read,
            write,
            *_,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def test_the_operations_are_its_tools_and_a_call_runs_one(monkeypatch, calls):
    _policy(monkeypatch, {})
    async with _session() as session:
        tools = (await session.list_tools()).tools
        result = await session.call_tool("getStatData", {"ids": "123"})

    assert {tool.name for tool in tools} == {"getStatData", "deleteCounter"}
    assert result.content[0].text == "42 visits"
    assert calls == [("getStatData", {"ids": "123"})]


async def test_a_tool_the_policy_denies_is_not_offered(monkeypatch, calls):
    _policy(monkeypatch, {"tools": {"denied": ["deleteCounter"]}})
    async with _session() as session:
        tools = (await session.list_tools()).tools

    assert [tool.name for tool in tools] == ["getStatData"]


async def test_an_unknown_tool_is_an_error_and_runs_nothing(monkeypatch, calls):
    _policy(monkeypatch, {})
    async with _session() as session:
        result = await session.call_tool("nope", {})

    assert result.is_error
    assert calls == []
