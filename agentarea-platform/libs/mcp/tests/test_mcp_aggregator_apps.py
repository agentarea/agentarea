"""The aggregator's two views of a member's tools, and its MCP Apps passthrough.

Agents get the model's view: tools the model may see, no ``_meta``. A client's
host gets the app view: the same tools with their ``_meta.ui`` (resource URIs
namespaced), plus the app-only tools of every app the client carries.
"""

from contextlib import asynccontextmanager

import pytest
from agentarea_mcp.application.mcp_aggregator import (
    AggregatedMember,
    MCPAggregatorProxy,
    namespaced_resource_uri,
)
from mcp.types import (
    ListResourcesResult,
    ReadResourceResult,
    Resource,
    TextResourceContents,
)

APP_MIME = "text/html;profile=mcp-app"

BOARD = {
    "name": "show_task_board",
    "description": "Show the board",
    "inputSchema": {"type": "object"},
    "_meta": {"ui": {"resourceUri": "ui://tasks/board.html"}},
}
SNAPSHOT = {
    "name": "get_board_snapshot",
    "description": "Board state for the view",
    "inputSchema": {"type": "object"},
    "_meta": {"ui": {"resourceUri": "ui://tasks/board.html", "visibility": ["app"]}},
}
UPDATE = {"name": "update_task", "description": "Update a task", "inputSchema": {"type": "object"}}
HIDDEN = {
    "name": "nobody",
    "description": "",
    "inputSchema": {"type": "object"},
    "_meta": {"ui": {"visibility": []}},
}


def _proxy(members, tools_by_member, names=None):
    proxy = MCPAggregatorProxy(
        name="c",
        description="",
        members=members,
        instance_urls={str(m.mcp_instance_id): "http://mcp-x:8000" for m in members},
        instance_names=names or {},
    )

    async def discover(member):
        return [dict(tool) for tool in tools_by_member[str(member.mcp_instance_id)]]

    proxy._discover_member_tools = discover
    return proxy


def _tasks(allowed=None):
    return AggregatedMember(mcp_instance_id="t", namespace_prefix="tasks", allowed_tools=allowed)


def test_a_resource_uri_namespaces_and_maps_back():
    member = _tasks()
    proxy = _proxy([member], {"t": []})

    uri = namespaced_resource_uri("tasks", "ui://tasks/board.html")

    assert uri == "ui://tasks/tasks/board.html"
    assert proxy.resource_owner(uri) == (member, "ui://tasks/board.html")
    assert proxy.resource_owner("ui://other/board.html") is None
    assert proxy.resource_owner("https://tasks/board.html") is None


def test_only_ui_uris_namespace():
    assert namespaced_resource_uri("tasks", "https://example.com/x") is None


async def test_the_model_view_is_unchanged():
    proxy = _proxy([_tasks()], {"t": [BOARD, SNAPSHOT, UPDATE, HIDDEN]})

    assert await proxy.list_namespaced_tools() == [
        {
            "name": "tasks__show_task_board",
            "description": "Show the board",
            "inputSchema": {"type": "object"},
        },
        {
            "name": "tasks__update_task",
            "description": "Update a task",
            "inputSchema": {"type": "object"},
        },
    ]


async def test_build_server_serves_the_model_view():
    proxy = _proxy([_tasks()], {"t": [BOARD, SNAPSHOT, UPDATE]})

    server = await proxy.build_server()

    assert sorted(tool.name for tool in await server.list_tools()) == [
        "tasks__show_task_board",
        "tasks__update_task",
    ]


async def test_the_app_view_carries_ui_meta_and_app_only_tools():
    proxy = _proxy([_tasks()], {"t": [BOARD, SNAPSHOT, UPDATE, HIDDEN]})

    tools = {tool["name"]: tool for tool in await proxy.list_app_tools()}

    assert set(tools) == {
        "tasks__show_task_board",
        "tasks__get_board_snapshot",
        "tasks__update_task",
    }
    assert tools["tasks__show_task_board"]["_meta"] == {
        "ui": {"resourceUri": "ui://tasks/tasks/board.html"}
    }
    assert tools["tasks__get_board_snapshot"]["_meta"] == {
        "ui": {"resourceUri": "ui://tasks/tasks/board.html", "visibility": ["app"]}
    }
    assert "_meta" not in tools["tasks__update_task"]


async def test_a_non_ui_resource_uri_is_not_exposed():
    odd = {**BOARD, "_meta": {"ui": {"resourceUri": "https://evil.example/x"}}}
    proxy = _proxy([_tasks()], {"t": [odd]})

    [tool] = await proxy.list_app_tools()

    assert "_meta" not in tool


async def test_app_only_tools_ride_with_an_attached_app_past_allowed_tools():
    # The picker narrows the model's tools; the app's own tools follow the app.
    member = _tasks(allowed=frozenset({"show_task_board"}))
    proxy = _proxy([member], {"t": [BOARD, SNAPSHOT, UPDATE]})

    names = {tool["name"] for tool in await proxy.list_app_tools()}

    assert names == {"tasks__show_task_board", "tasks__get_board_snapshot"}
    assert proxy.owner_of("tasks__get_board_snapshot") == (member, "get_board_snapshot")
    assert proxy.owner_of("tasks__update_task") is None


async def test_without_an_attached_app_its_app_only_tools_are_not_served():
    member = _tasks(allowed=frozenset({"update_task"}))
    proxy = _proxy([member], {"t": [BOARD, SNAPSHOT, UPDATE]})

    names = {tool["name"] for tool in await proxy.list_app_tools()}

    assert names == {"tasks__update_task"}
    assert await proxy.resolve_tool("tasks__update_task") == "tasks__update_task"
    with pytest.raises(ValueError, match="No member owns tool get_board_snapshot"):
        await proxy.resolve_tool("get_board_snapshot")
    with pytest.raises(ValueError, match="No member owns tool tasks__get_board_snapshot"):
        await proxy.resolve_tool("tasks__get_board_snapshot")


async def test_an_app_only_tool_alone_does_not_attach_its_app():
    proxy = _proxy([_tasks()], {"t": [SNAPSHOT, UPDATE]})

    assert {tool["name"] for tool in await proxy.list_app_tools()} == {"tasks__update_task"}


async def test_a_raw_name_resolves_to_the_one_member_serving_it():
    proxy = _proxy([_tasks()], {"t": [BOARD, SNAPSHOT, UPDATE]})

    assert await proxy.resolve_tool("update_task") == "tasks__update_task"
    assert await proxy.resolve_tool("get_board_snapshot") == "tasks__get_board_snapshot"
    assert await proxy.resolve_tool("tasks__show_task_board") == "tasks__show_task_board"


async def test_a_raw_name_two_members_serve_is_ambiguous():
    members = [
        _tasks(),
        AggregatedMember(mcp_instance_id="o", namespace_prefix="other"),
    ]
    proxy = _proxy(members, {"t": [BOARD, UPDATE], "o": [UPDATE]})

    with pytest.raises(ValueError, match="other__update_task, tasks__update_task"):
        await proxy.resolve_tool("update_task")


async def test_an_unknown_name_resolves_to_nothing():
    proxy = _proxy([_tasks()], {"t": [BOARD]})

    with pytest.raises(ValueError, match="No member owns tool nope"):
        await proxy.resolve_tool("nope")


class _FakeMemberClient:
    def __init__(self, resources, reads):
        self.resources = resources
        self.reads = reads
        self.read_uris: list[str] = []

    async def list_resources(self):
        return ListResourcesResult(resources=self.resources)

    async def read_resource(self, uri):
        self.read_uris.append(uri)
        return self.reads[uri]


def _dial(proxy, clients):
    dialed: list[str] = []

    @asynccontextmanager
    async def dial(member, _timeout):
        dialed.append(str(member.mcp_instance_id))
        yield clients[str(member.mcp_instance_id)]

    proxy._dial = dial
    return dialed


async def test_resources_list_the_ui_resources_of_attached_apps_namespaced():
    members = [_tasks(), AggregatedMember(mcp_instance_id="o", namespace_prefix="other")]
    proxy = _proxy(members, {"t": [BOARD, UPDATE], "o": [UPDATE]})
    board = Resource(name="board", uri="ui://tasks/board.html", mime_type=APP_MIME)
    data = Resource(name="data", uri="file:///data.json")
    dialed = _dial(proxy, {"t": _FakeMemberClient([board, data], {})})

    resources = await proxy.list_app_resources()

    assert [(r.name, r.uri, r.mime_type) for r in resources] == [
        ("board", "ui://tasks/tasks/board.html", APP_MIME)
    ]
    assert dialed == ["t"]


async def test_reading_a_namespaced_resource_reads_the_member_and_answers_namespaced():
    proxy = _proxy([_tasks()], {"t": [BOARD]})
    contents = TextResourceContents(
        uri="ui://tasks/board.html",
        mime_type=APP_MIME,
        text="<html></html>",
        _meta={"ui": {"prefersBorder": True}},
    )
    member_client = _FakeMemberClient(
        [], {"ui://tasks/board.html": ReadResourceResult(contents=[contents])}
    )
    _dial(proxy, {"t": member_client})

    result = await proxy.read_app_resource("ui://tasks/tasks/board.html")

    assert result is not None
    [read] = result.contents
    assert isinstance(read, TextResourceContents)
    assert (read.uri, read.mime_type, read.text) == (
        "ui://tasks/tasks/board.html",
        APP_MIME,
        "<html></html>",
    )
    assert read.meta == {"ui": {"prefersBorder": True}}
    assert member_client.read_uris == ["ui://tasks/board.html"]


async def test_a_resource_no_attached_app_owns_reads_as_nothing():
    proxy = _proxy([_tasks(allowed=frozenset({"update_task"}))], {"t": [BOARD, UPDATE]})
    dialed = _dial(proxy, {})

    assert await proxy.read_app_resource("ui://tasks/tasks/board.html") is None
    assert await proxy.read_app_resource("ui://nobody/board.html") is None
    assert await proxy.read_app_resource("https://tasks/board.html") is None
    assert dialed == []
