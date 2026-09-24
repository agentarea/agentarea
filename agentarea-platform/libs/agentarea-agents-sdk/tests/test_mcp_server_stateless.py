"""The native MCP server serves both handshake and per-request protocol eras."""

import json

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from agentarea_agents_sdk.mcp_server import create_mcp_server, mount_mcp_app
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method

_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
_INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1"},
    },
}


class _EchoToolset(Toolset):
    @tool_method
    async def echo(self, text: str) -> str:
        """Return the text unchanged."""
        return text


def _server_app(server):
    return server.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


def _sse_payload(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data frame in response: {body!r}")


@pytest.mark.asyncio
async def test_legacy_requests_work_without_a_session_header():
    server = create_mcp_server(toolsets=[_EchoToolset()], name="Test", workspace_argument=False)
    app = _server_app(server)
    headers = {**_HEADERS, "MCP-Protocol-Version": "2025-11-25"}

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initialize = await client.post("/", json=_INITIALIZE, headers=headers)
            assert initialize.status_code == 200
            assert "mcp-session-id" not in initialize.headers

            listed = await client.post(
                "/",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers=headers,
            )

    assert listed.status_code == 200
    assert "mcp-session-id" not in listed.headers
    payload = _sse_payload(listed.text)
    assert "error" not in payload, payload
    names = [tool["name"] for tool in payload["result"]["tools"]]
    assert len(names) == 1
    assert names[0].endswith("echo")


@pytest.mark.asyncio
async def test_modern_client_discovers_and_lists_tools_without_a_session_header():
    server = create_mcp_server(toolsets=[_EchoToolset()], name="Test", workspace_argument=False)
    app = _server_app(server)
    responses = []

    async def record_response(response):
        responses.append(response)

    async with server.session_manager.run():
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://test",
            event_hooks={"response": [record_response]},
        ) as http_client:
            async with Client(
                streamable_http_client("http://test/", http_client=http_client)
            ) as client:
                assert client.protocol_version == "2026-07-28"
                listed = await client.list_tools()

    assert [tool.name for tool in listed.tools] == ["__echo_echo"]
    assert responses
    assert all("mcp-session-id" not in response.headers for response in responses)


@pytest.mark.asyncio
async def test_mount_root_is_served_without_a_redirect():
    """POST to the mount root must be answered, not redirected."""
    server = create_mcp_server(toolsets=[_EchoToolset()], name="Test", workspace_argument=False)
    app = FastAPI()
    mount_mcp_app(app, "/mcp", _server_app(server))
    headers = {**_HEADERS, "MCP-Protocol-Version": "2025-11-25"}

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            without_slash = await client.post("/mcp", json=_INITIALIZE, headers=headers)
            with_slash = await client.post("/mcp/", json=_INITIALIZE, headers=headers)

    assert without_slash.status_code == 200
    assert with_slash.status_code == 200
