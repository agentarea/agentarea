"""A mount's ``?toolsets=`` parameter narrows what a harness sees and may call."""

import json

import httpx
import pytest
from mcp.server.transport_security import TransportSecuritySettings

from agentarea_agents_sdk.mcp_server import (
    ToolsetSelectionMiddleware,
    UnknownToolsetError,
    create_mcp_server,
)
from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import ToolsetMetadata

_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "MCP-Protocol-Version": "2025-11-25",
}


class _NotesToolset(Toolset):
    # Metadata without @toolset: registering would leak into the global catalog.
    __toolset_meta__ = ToolsetMetadata(namespace="test/notes")

    @tool_method
    async def read(self, title: str) -> str:
        """Read a note."""
        return f"note {title}"

    @tool_method
    async def erase(self, title: str) -> str:
        """Erase a note."""
        return f"erased {title}"


class ClockToolset(Toolset):
    @tool_method
    async def now(self) -> str:
        """Tell the time."""
        return "noon"


def _server():
    return create_mcp_server(
        toolsets=[_NotesToolset(), ClockToolset()], name="Test", workspace_argument=False
    )


async def _post(path: str, payload: dict) -> httpx.Response:
    server = _server()
    app = ToolsetSelectionMiddleware(
        server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        ),
        server,
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.post(path, json=payload, headers=_HEADERS)


def _result(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])["result"]
    raise AssertionError(f"no SSE data frame in response: {response.text!r}")


async def _listed(path: str) -> set[str]:
    response = await _post(path, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {tool["name"] for tool in _result(response)["tools"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", {"notes_read", "notes_erase", "clock_now"}),
        ("/?toolsets=clock", {"clock_now"}),
        ("/?toolsets=test/notes", {"notes_read", "notes_erase"}),
        ("/?toolsets=notes,%20clock", {"notes_read", "notes_erase", "clock_now"}),
    ],
    ids=["all-without-param", "by-name", "by-namespace", "several"],
)
async def test_the_param_lists_only_the_named_toolsets(path, expected):
    assert await _listed(path) == expected


@pytest.mark.asyncio
async def test_a_tool_outside_the_selection_cannot_be_called():
    call = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "notes_erase", "arguments": {"title": "plans"}},
    }

    refused = _result(await _post("/?toolsets=clock", call))
    served = _result(await _post("/?toolsets=notes", call))

    assert refused["isError"] is True
    assert "Unknown tool" in refused["content"][0]["text"]
    assert served["content"][0]["text"] == "erased plans"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["toolsets=clock,calendar", "toolsets="])
async def test_a_selection_naming_no_known_toolset_is_refused(query):
    response = await _post(f"/?{query}", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response.status_code == 400
    message = response.json()["error"]["message"]
    assert "notes" in message
    assert "clock" in message


def test_disabling_a_method_the_toolset_lacks_is_refused():
    with pytest.raises(UnknownToolsetError, match="no method"):
        _server().select({"notes": ["shred"]})
