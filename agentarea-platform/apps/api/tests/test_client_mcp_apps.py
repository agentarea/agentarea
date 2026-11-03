"""A client's endpoint passes its MCP Apps through to the host.

An external host (Claude, ChatGPT, VS Code) renders the ``ui://`` resource a
tool names, and the app calls its tools back by the raw names it knows. Those
calls run the same governed path as a namespaced one, judged under the
namespaced name.
"""

from contextlib import asynccontextmanager
from typing import Any

import pytest
from agentarea_api.api.v1 import client_mcp
from agentarea_common.auth.context import UserContext
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from mcp.server.apps import EXTENSION_ID
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListResourcesResult,
    ReadResourceRequestParams,
    ReadResourceResult,
    Resource,
    TextContent,
    TextResourceContents,
)

CLIENT_ID = "55555555-5555-5555-5555-555555555555"
TASKS_ID = "66666666-6666-6666-6666-666666666666"
OTHER_ID = "77777777-7777-7777-7777-777777777777"
APP_MIME = "text/html;profile=mcp-app"

TASKS_TOOLS = [
    {
        "name": "show_task_board",
        "description": "Show the board",
        "inputSchema": {"type": "object"},
        "_meta": {"ui": {"resourceUri": "ui://tasks/board.html"}},
    },
    {
        "name": "get_board_snapshot",
        "description": "Board state for the view",
        "inputSchema": {"type": "object"},
        "_meta": {"ui": {"resourceUri": "ui://tasks/board.html", "visibility": ["app"]}},
    },
    {"name": "update_task", "description": "Update a task", "inputSchema": {"type": "object"}},
]
OTHER_TOOLS = [{"name": "update_task", "description": "", "inputSchema": {"type": "object"}}]


class _MemberClient:
    def __init__(self) -> None:
        self.read_uris: list[str] = []

    async def list_resources(self):
        return ListResourcesResult(
            resources=[
                Resource(name="board", uri="ui://tasks/board.html", mime_type=APP_MIME),
                Resource(name="notes", uri="file:///notes.md"),
            ]
        )

    async def read_resource(self, uri):
        self.read_uris.append(uri)
        return ReadResourceResult(
            contents=[TextResourceContents(uri=uri, mime_type=APP_MIME, text="<html></html>")]
        )


class _Gateway:
    def __init__(self, monkeypatch) -> None:
        self.monkeypatch = monkeypatch
        self.upstream: list[tuple[str, str, dict[str, Any]]] = []
        self.signed: list[str] = []
        self.audited: list[str] = []
        self.member_client = _MemberClient()

    def carry(
        self,
        *,
        allowed: frozenset[str] | None = None,
        other: bool = False,
        policy: dict | None = None,
    ) -> None:
        members = [
            AggregatedMember(
                mcp_instance_id=TASKS_ID,
                namespace_prefix="tasks",
                pinned=False,
                allowed_tools=allowed,
            )
        ]
        tools = {TASKS_ID: TASKS_TOOLS}
        if other:
            members.append(
                AggregatedMember(mcp_instance_id=OTHER_ID, namespace_prefix="other", pinned=False)
            )
            tools[OTHER_ID] = OTHER_TOOLS
        proxy = MCPAggregatorProxy(
            "Claude",
            "",
            members,
            {str(m.mcp_instance_id): "http://tasks.invalid/mcp" for m in members},
            {TASKS_ID: "Tasks", OTHER_ID: "Other"},
            era_verdict_store=object(),
        )

        async def discover(member):
            return [dict(tool) for tool in tools[str(member.mcp_instance_id)]]

        async def call_member(member, tool_name, arguments):
            self.upstream.append((str(member.mcp_instance_id), tool_name, arguments))
            return CallToolResult(content=[TextContent(type="text", text=f"ran {tool_name}")])

        @asynccontextmanager
        async def dial(_member, _timeout):
            yield self.member_client

        self.monkeypatch.setattr(proxy, "_discover_member_tools", discover)
        self.monkeypatch.setattr(proxy, "_call_member_tool_result", call_member)
        self.monkeypatch.setattr(proxy, "_dial", dial)

        scope = client_mcp.ClientScope(
            proxy=proxy,
            skill_registry={},
            platform_tools=frozenset(),
            user_context=UserContext(user_id="user-1", workspace_id="client-ws"),
            tool_policy=policy or {},
            actor_type="user",
            client_id=CLIENT_ID,
        )

        async def resolve(_client_id):
            return scope

        self.monkeypatch.setattr(client_mcp, "_resolve_client_scope", resolve)


@pytest.fixture
def gateway(monkeypatch):
    gw = _Gateway(monkeypatch)
    real_headers = client_mcp._caller_headers

    def caller_headers(scope, name):
        gw.signed.append(name)
        return real_headers(scope, name)

    async def audit(_scope, tool_name, *_args, **_kwargs):
        gw.audited.append(tool_name)

    monkeypatch.setattr(client_mcp, "_caller_headers", caller_headers)
    monkeypatch.setattr(client_mcp, "_audit_tool_call", audit)
    token = client_mcp._client_id_var.set(CLIENT_ID)
    yield gw
    client_mcp._client_id_var.reset(token)


async def _call(name: str, **arguments) -> CallToolResult:
    return await client_mcp._call_tool(None, CallToolRequestParams(name=name, arguments=arguments))


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


async def test_tools_carry_their_ui_meta_with_namespaced_resource_uris(gateway):
    gateway.carry()

    listed = {tool.name: tool for tool in (await client_mcp._list_tools(None, None)).tools}

    assert set(listed) == {
        "tasks__show_task_board",
        "tasks__get_board_snapshot",
        "tasks__update_task",
    }
    assert listed["tasks__show_task_board"].meta == {
        "ui": {"resourceUri": "ui://tasks/tasks/board.html"}
    }
    assert listed["tasks__get_board_snapshot"].meta == {
        "ui": {"resourceUri": "ui://tasks/tasks/board.html", "visibility": ["app"]}
    }
    assert listed["tasks__update_task"].meta is None


async def test_the_policy_still_filters_every_listed_tool(gateway):
    gateway.carry(policy={"tools": {"denied": ["get_board_snapshot"]}})

    listed = [tool.name for tool in (await client_mcp._list_tools(None, None)).tools]

    assert listed == ["tasks__show_task_board", "tasks__update_task"]


async def test_an_app_calls_its_tool_by_raw_name_through_the_governed_path(gateway):
    gateway.carry()

    result = await _call("update_task", id="t-1")

    assert _text(result) == "ran update_task"
    assert gateway.upstream == [(TASKS_ID, "update_task", {"id": "t-1"})]
    assert gateway.audited == ["tasks__update_task"]
    assert gateway.signed == ["tasks__update_task"]


async def test_a_raw_name_call_answers_to_the_namespaced_policy(gateway):
    gateway.carry(policy={"tools": {"denied": [f"mcp:{TASKS_ID}:update_task"]}})

    result = await _call("update_task", id="t-1")

    assert result.is_error is True
    assert "denied by policy" in _text(result)
    assert gateway.upstream == []
    assert gateway.audited == ["tasks__update_task"]


async def test_an_app_only_tool_runs_while_its_app_is_attached(gateway):
    gateway.carry(allowed=frozenset({"show_task_board"}))

    result = await _call("get_board_snapshot")

    assert _text(result) == "ran get_board_snapshot"
    assert gateway.upstream == [(TASKS_ID, "get_board_snapshot", {})]
    assert gateway.audited == ["tasks__get_board_snapshot"]


async def test_an_app_only_tool_is_unreachable_without_its_app(gateway):
    gateway.carry(allowed=frozenset({"update_task"}))

    with pytest.raises(ValueError, match="No member owns tool get_board_snapshot"):
        await _call("get_board_snapshot")
    with pytest.raises(ValueError, match="No member owns tool tasks__get_board_snapshot"):
        await _call("tasks__get_board_snapshot")
    assert gateway.upstream == []


async def test_a_raw_name_two_connections_serve_names_the_alternatives(gateway):
    gateway.carry(other=True)

    with pytest.raises(ValueError, match="other__update_task, tasks__update_task"):
        await _call("update_task")
    assert gateway.upstream == []


async def test_an_unknown_raw_name_is_refused(gateway):
    gateway.carry()

    with pytest.raises(ValueError, match="No member owns tool nope"):
        await _call("nope")


async def test_resources_list_the_carried_apps_ui_resources_namespaced(gateway):
    gateway.carry()

    listed = await client_mcp._list_resources(None, None)

    assert [(r.uri, r.mime_type) for r in listed.resources] == [
        ("ui://tasks/tasks/board.html", APP_MIME)
    ]


async def test_reading_a_resource_routes_to_its_member(gateway):
    gateway.carry()

    result = await client_mcp._read_resource(
        None, ReadResourceRequestParams(uri="ui://tasks/tasks/board.html")
    )

    assert isinstance(result, ReadResourceResult)
    [content] = result.contents
    assert isinstance(content, TextResourceContents)
    assert (content.uri, content.mime_type) == ("ui://tasks/tasks/board.html", APP_MIME)
    assert gateway.member_client.read_uris == ["ui://tasks/board.html"]


async def test_a_resource_no_carried_app_owns_is_an_mcp_error(gateway):
    gateway.carry()

    with pytest.raises(MCPError) as raised:
        await client_mcp._read_resource(None, ReadResourceRequestParams(uri="ui://nope/x.html"))
    assert raised.value.code == INVALID_PARAMS
    assert gateway.member_client.read_uris == []


async def test_a_caller_who_may_not_use_the_client_reads_nothing(monkeypatch):
    async def denied(_client_id):
        raise client_mcp.ClientAccessDeniedError(CLIENT_ID)

    monkeypatch.setattr(client_mcp, "_resolve_client_scope", denied)
    token = client_mcp._client_id_var.set(CLIENT_ID)
    try:
        with pytest.raises(ValueError, match="Not authorized"):
            await client_mcp._list_resources(None, None)
        with pytest.raises(ValueError, match="Not authorized"):
            await client_mcp._read_resource(
                None, ReadResourceRequestParams(uri="ui://tasks/tasks/board.html")
            )
    finally:
        client_mcp._client_id_var.reset(token)


def test_the_endpoint_declares_mcp_apps_and_resources():
    capabilities = client_mcp.client_mcp_server.get_capabilities()

    assert capabilities.extensions is not None
    assert capabilities.extensions[EXTENSION_ID] == {}
    assert capabilities.resources is not None


async def test_templates_list_is_empty():
    assert (await client_mcp._list_resource_templates(None, None)).resource_templates == []
