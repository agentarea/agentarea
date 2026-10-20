"""Every platform MCP server serves the events extension and advertises it both ways."""

from types import SimpleNamespace

import pytest
from agentarea_api.mcp_events import ClientScope, PinnedScope, install_mcp_events
from agentarea_api.platform_mcp import create_platform_mcp_server
from agentarea_streams.domain.mcp_events import EXTENSION_ID, ErrorCode, EventsError
from mcp.server.lowlevel import Server

METHODS = ("events/list", "events/poll", "events/subscribe", "events/unsubscribe")


@pytest.mark.parametrize("spanning", [True, False])
def test_both_platform_servers_serve_the_events_methods(spanning):
    lowlevel = create_platform_mcp_server(spanning=spanning)._lowlevel_server  # pyright: ignore[reportPrivateUsage]
    assert all(lowlevel.get_request_handler(method) is not None for method in METHODS)
    assert lowlevel.extensions[EXTENSION_ID] == {"listChanged": False}


def test_the_client_server_serves_them_too():
    from agentarea_api.api.v1.client_mcp import client_mcp_server

    assert all(client_mcp_server.get_request_handler(method) is not None for method in METHODS)


@pytest.mark.parametrize("method", ["initialize", "server/discover"])
async def test_the_handshake_advertises_the_extension_and_the_sketch_key(method):
    server = Server("t")
    install_mcp_events(server, PinnedScope())

    async def call_next(ctx):
        return {"capabilities": {"tools": {}}}

    result = await server.middleware[-1](SimpleNamespace(method=method), call_next)
    assert result["capabilities"]["extensions"][EXTENSION_ID] == {"listChanged": False}
    assert result["capabilities"]["events"] == {"listChanged": False}
    assert result["capabilities"]["tools"] == {}


async def test_other_results_are_left_alone():
    server = Server("t")
    install_mcp_events(server, PinnedScope())

    async def call_next(ctx):
        return {"tools": []}

    assert await server.middleware[-1](SimpleNamespace(method="tools/list"), call_next) == {
        "tools": []
    }


async def test_a_client_the_caller_cannot_use_is_forbidden():
    async def nobody():
        return None

    with pytest.raises(EventsError) as raised:
        await ClientScope(nobody).workspaces()
    assert raised.value.code == ErrorCode.FORBIDDEN
