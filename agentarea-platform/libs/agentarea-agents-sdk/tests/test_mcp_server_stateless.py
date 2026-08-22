"""The native MCP server must serve every request without a prior session.

The API runs as several replicas behind an ingress with no session affinity, so
an ``initialize`` handled by one replica leaves the follow-up ``tools/list`` on
another replica with no in-memory session to resume — the client then sees
"Session not found" and the connection is closed before any tool is listed.
"""

import json

import httpx
import pytest
from fastapi import FastAPI

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
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1"},
    },
}


class _EchoToolset(Toolset):
    @tool_method
    async def echo(self, text: str) -> str:
        """Return the text unchanged."""
        return text


def _sse_payload(body: str) -> dict:
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data frame in response: {body!r}")


@pytest.mark.asyncio
async def test_tools_list_does_not_need_the_initialize_session():
    server = create_mcp_server(toolsets=[_EchoToolset()], name="Test")
    app = server.streamable_http_app()

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            initialize = await client.post("/", json=_INITIALIZE, headers=_HEADERS)
            assert initialize.status_code == 200
            assert "mcp-session-id" not in initialize.headers

            # No session header on purpose: this is the request as a second
            # replica receives it.
            listed = await client.post(
                "/",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                headers=_HEADERS,
            )

    assert listed.status_code == 200
    payload = _sse_payload(listed.text)
    assert "error" not in payload, payload
    names = [tool["name"] for tool in payload["result"]["tools"]]
    assert len(names) == 1
    assert names[0].endswith("echo")


@pytest.mark.asyncio
async def test_mount_root_is_served_without_a_redirect():
    """POST to the mount root must be answered, not redirected.

    ``app.mount("/mcp", …)`` alone makes Starlette 307 ``/mcp`` to ``/mcp/``.
    The advertised resource identifier has no trailing slash, so a client that
    binds its token to the URL it ends up posting to and a server that checks
    the audience against the advertised one disagree by one character.
    """
    server = create_mcp_server(toolsets=[_EchoToolset()], name="Test")
    app = FastAPI()
    mount_mcp_app(app, "/mcp", server.streamable_http_app())

    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            without_slash = await client.post("/mcp", json=_INITIALIZE, headers=_HEADERS)
            with_slash = await client.post("/mcp/", json=_INITIALIZE, headers=_HEADERS)

    assert without_slash.status_code == 200
    assert with_slash.status_code == 200
