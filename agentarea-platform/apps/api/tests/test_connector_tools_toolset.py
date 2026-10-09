"""``tools_search`` and ``tools_call``: a connector's tools, reached through ``/mcp`` itself.

Search ranks the stored tools of the workspace's verified connectors the caller
may read. Call runs one of them through the dispatch a registered client's
endpoint uses — the workspace policy, the audit trail, the connection's
resolved credentials — as the signed-in person, and holds a destructive tool
until the person confirms.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import agentarea_mcp.application.service as mcp_service
import pytest
from agentarea_agents_sdk.mcp_server.auth import use_mcp_user_context
from agentarea_api.api.v1 import client_mcp, mcp_oauth_connect
from agentarea_api.tools import connector_tools_toolset
from agentarea_api.tools.connector_tools_toolset import ConnectorToolsToolset
from agentarea_common.audit import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_mcp.application.mcp_aggregator import MCPAggregatorProxy
from fastapi import HTTPException
from mcp.types import CallToolResult, TextContent

importlib.import_module("agentarea_agents.domain.skill_models")

CALLER = UserContext(user_id="user-a", workspace_id="ws-a", workspace_slug="acme")
VERIFIED = {"status": "succeeded"}


def _tool(name: str, description: str = "", **annotations: Any) -> dict[str, Any]:
    tool: dict[str, Any] = {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }
    if annotations:
        tool["annotations"] = annotations
    return tool


def _operation(path: str, method: str, operation_id: str) -> dict[str, Any]:
    return {path: {method: {"operationId": operation_id, "summary": operation_id}}}


def _connection(
    name: str,
    tools: list[dict],
    paths: dict | None = None,
    *,
    status: str = "active",
    registry_item_id: Any = None,
    auth_config_id: Any = None,
):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        status=status,
        available_tools=tools,
        spec_content={"openapi": "3.0.0", "paths": paths or {}},
        custom_query_params=[],
        registry_item_id=registry_item_id,
        auth_config_id=auth_config_id,
    )


def _instance(name: str, tools: list[dict], verification: dict | None = None):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        description=None,
        verification=VERIFIED if verification is None else verification,
        server_spec_id=str(uuid4()),
        tools=tools,
    )


@pytest.fixture
def harness(monkeypatch):
    """The toolset over a stubbed instance service; each test sets the instances."""

    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), CALLER, MagicMock(), AsyncMock(), AsyncMock()

    monkeypatch.setattr(connector_tools_toolset, "platform_context", _ctx)
    monkeypatch.setattr(connector_tools_toolset, "platform_read_context", _ctx)
    monkeypatch.setattr(
        mcp_oauth_connect,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(APP_URL="https://app.example")),
    )
    service = MagicMock()
    service.needs_connecting = AsyncMock(return_value=False)
    monkeypatch.setattr(mcp_service, "MCPServerInstanceService", lambda **_kwargs: service)
    state = SimpleNamespace(service=service, readable=None, instances=[])

    async def _list():
        return state.instances

    service.list = _list
    openapi = MagicMock()
    openapi.resolve_headers = AsyncMock(return_value={})
    state.openapi = openapi
    state.connections = []

    async def _list_connections(**_kwargs):
        return state.connections, len(state.connections)

    openapi.list_connections = _list_connections

    async def _openapi_service(*_args):
        return openapi

    monkeypatch.setattr(connector_tools_toolset, "get_openapi_connection_service", _openapi_service)

    async def _readable(_user_id):
        if state.readable is None:
            return {str(i.id) for i in [*state.instances, *state.connections]}
        return state.readable

    monkeypatch.setattr(connector_tools_toolset, "readable_resource_ids", _readable)
    monkeypatch.setattr(connector_tools_toolset, "require_permission", AsyncMock())
    state.dispatch = AsyncMock(
        return_value=CallToolResult(content=[TextContent(type="text", text="ok")])
    )
    monkeypatch.setattr(client_mcp, "call_instance_tool", state.dispatch)
    state.openapi_dispatch = AsyncMock(
        return_value=CallToolResult(content=[TextContent(type="text", text="ok")])
    )
    monkeypatch.setattr(client_mcp, "call_openapi_tool", state.openapi_dispatch)
    with use_mcp_user_context(CALLER):
        yield state


async def _search(**kwargs) -> dict:
    return json.loads(await ConnectorToolsToolset().search(**kwargs))


async def _call(**kwargs) -> dict:
    return json.loads(await ConnectorToolsToolset().call(**kwargs))


# --- search -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_ranks_name_matches_above_description_matches(harness):
    wiki = _instance(
        "DeepWiki",
        [
            _tool("ask_question", "Ask anything about a repository"),
            _tool("read_wiki_structure", "List the documentation topics of a repository"),
            _tool("read_wiki_contents", "View a repository's wiki"),
        ],
    )
    harness.instances = [wiki]

    result = await _search(query="wiki structure")

    assert [r["tool"] for r in result["results"]] == [
        "read_wiki_structure",
        "read_wiki_contents",
    ]
    assert result["searched_connectors"] == 1
    first = result["results"][0]
    assert first == {
        "connector_id": str(wiki.id),
        "connector": "DeepWiki",
        "tool": "read_wiki_structure",
        "description": "List the documentation topics of a repository",
        "hint": None,
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }


@pytest.mark.asyncio
async def test_an_exact_name_ranks_first(harness):
    harness.instances = [
        _instance(
            "Tracker",
            [
                _tool("list_campaigns_archived", "list campaigns that were archived"),
                _tool("list_campaigns", "Lists campaigns"),
            ],
        )
    ]

    result = await _search(query="list_campaigns")

    assert result["results"][0]["tool"] == "list_campaigns"


@pytest.mark.asyncio
async def test_a_description_only_match_is_found_and_misses_are_not(harness):
    harness.instances = [
        _instance("Mail", [_tool("send", "Send an email message"), _tool("noop", "Nothing")])
    ]

    result = await _search(query="email")

    assert [r["tool"] for r in result["results"]] == ["send"]


@pytest.mark.asyncio
async def test_search_honours_the_limit(harness):
    harness.instances = [_instance("Mail", [_tool(f"send_{i}", "send") for i in range(5)])]

    result = await _search(query="send", limit=2)

    assert len(result["results"]) == 2


@pytest.mark.asyncio
async def test_search_covers_verified_connectors_only(harness):
    verified = _instance("A", [_tool("search_docs")])
    failed = _instance("B", [_tool("search_docs")], {"status": "failed"})
    pending = _instance("C", [_tool("search_docs")], {})
    harness.instances = [verified, failed, pending]

    result = await _search(query="search docs")

    assert [r["connector"] for r in result["results"]] == ["A"]
    assert result["searched_connectors"] == 1


@pytest.mark.asyncio
async def test_search_covers_only_connectors_the_caller_may_read(harness):
    mine = _instance("Mine", [_tool("search_docs")])
    hidden = _instance("Hidden", [_tool("search_docs")])
    harness.instances = [mine, hidden]
    harness.readable = {str(mine.id)}

    result = await _search(query="search")

    assert [r["connector"] for r in result["results"]] == ["Mine"]


@pytest.mark.asyncio
@pytest.mark.parametrize("by", ["id", "name"])
async def test_search_filters_by_connector_id_or_name(harness, by):
    a = _instance("Alpha", [_tool("search_docs")])
    b = _instance("Beta", [_tool("search_docs")])
    harness.instances = [a, b]

    result = await _search(query="search", connector=str(b.id) if by == "id" else "Beta")

    assert [r["connector"] for r in result["results"]] == ["Beta"]
    assert result["searched_connectors"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("annotations", "hint"),
    [
        ({"readOnlyHint": True}, "read-only"),
        ({"destructiveHint": True}, "destructive"),
        ({"read_only_hint": True}, "read-only"),
        ({"destructive_hint": True}, "destructive"),
        ({"readOnlyHint": True, "destructiveHint": True}, "destructive"),
        ({}, None),
    ],
)
async def test_search_reports_the_safety_hint_in_either_stored_spelling(harness, annotations, hint):
    harness.instances = [_instance("A", [_tool("delete_lead", "Delete a lead", **annotations)])]

    result = await _search(query="delete lead")

    assert result["results"][0]["hint"] == hint


@pytest.mark.asyncio
async def test_search_never_reaches_another_workspace(harness):
    """Readable in the graph is not enough: the workspace-scoped listing is the source."""
    here = _instance("Here", [_tool("search_docs")])
    harness.instances = [here]
    harness.readable = {str(here.id), str(uuid4())}

    result = await _search(query="search")

    assert result["searched_connectors"] == 1
    assert [r["connector_id"] for r in result["results"]] == [str(here.id)]


@pytest.mark.asyncio
async def test_search_covers_openapi_connections_alongside_mcp_connectors(harness):
    wiki = _instance("DeepWiki", [_tool("read_wiki_structure", "Topics of a wiki")])
    analytics = _connection(
        "Google Analytics Admin",
        [_tool("listAccounts", "List the accounts of the caller")],
        _operation("/v1/accounts", "get", "listAccounts"),
    )
    harness.instances = [wiki]
    harness.connections = [analytics]

    result = await _search(query="list accounts")

    assert result["searched_connectors"] == 2
    assert result["results"] == [
        {
            "connector_id": str(analytics.id),
            "connector": "Google Analytics Admin",
            "tool": "listAccounts",
            "description": "List the accounts of the caller",
            "hint": "read-only",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "hint"),
    [("get", "read-only"), ("delete", "destructive"), ("post", None), ("patch", None)],
)
async def test_an_openapi_tool_hint_follows_its_http_method(harness, method, hint):
    harness.connections = [
        _connection("Api", [_tool("doThing", "Do a thing")], _operation("/x", method, "doThing"))
    ]

    result = await _search(query="do thing")

    assert result["results"][0]["hint"] == hint


@pytest.mark.asyncio
async def test_search_skips_openapi_connections_the_caller_may_not_read_or_inactive(harness):
    mine = _connection("Mine", [_tool("search_docs")])
    hidden = _connection("Hidden", [_tool("search_docs")])
    off = _connection("Off", [_tool("search_docs")], status="disabled")
    harness.connections = [mine, hidden, off]
    harness.readable = {str(mine.id), str(off.id)}

    result = await _search(query="search")

    assert [r["connector"] for r in result["results"]] == ["Mine"]
    assert result["searched_connectors"] == 1


@pytest.mark.asyncio
async def test_search_filters_openapi_connections_by_name(harness):
    harness.instances = [_instance("Alpha", [_tool("search_docs")])]
    harness.connections = [_connection("Beta", [_tool("search_docs")])]

    result = await _search(query="search", connector="beta")

    assert [r["connector"] for r in result["results"]] == ["Beta"]


# --- call ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_call_dispatches_through_the_client_dispatch(harness):
    wiki = _instance("DeepWiki", [_tool("ask_question", readOnlyHint=True)])
    harness.instances = [wiki]
    harness.dispatch.return_value = CallToolResult(
        content=[TextContent(type="text", text="The answer")],
        structured_content={"answer": 42},
    )

    result = await _call(connector="DeepWiki", tool="ask_question", arguments={"q": "why"})

    assert result == {
        "connector_id": str(wiki.id),
        "connector": "DeepWiki",
        "tool": "ask_question",
        "content": [{"type": "text", "text": "The answer"}],
        "structuredContent": {"answer": 42},
    }
    _session, user_ctx, service, instance, tool, arguments = harness.dispatch.await_args.args
    assert (user_ctx, service, instance, tool, arguments) == (
        CALLER,
        harness.service,
        wiki,
        "ask_question",
        {"q": "why"},
    )
    connector_tools_toolset.require_permission.assert_awaited_once_with(
        "use", "mcp_instance", str(wiki.id), CALLER.user_id
    )


@pytest.mark.asyncio
async def test_an_upstream_error_is_reported_as_one(harness):
    harness.instances = [_instance("A", [_tool("t")])]
    harness.dispatch.return_value = CallToolResult(
        content=[TextContent(type="text", text="rate limited")], is_error=True
    )

    result = await _call(connector="A", tool="t")

    assert result["is_error"] is True
    assert result["content"] == [{"type": "text", "text": "rate limited"}]


@pytest.mark.asyncio
async def test_a_caller_without_use_is_refused_before_anything_runs(harness):
    harness.instances = [_instance("A", [_tool("t")])]
    connector_tools_toolset.require_permission.side_effect = HTTPException(
        status_code=403, detail="Permission denied"
    )

    result = await _call(connector="A", tool="t")

    assert result == {"error": "Permission denied"}
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_destructive_tool_waits_for_confirmation(harness):
    harness.instances = [_instance("Leads", [_tool("delete_lead", destructiveHint=True)])]

    result = await _call(connector="Leads", tool="delete_lead", arguments={"id": "1"})

    assert result == {
        "confirmation_required": True,
        "connector": "Leads",
        "tool": "delete_lead",
        "message": (
            "This tool is marked destructive. Ask the user to confirm, "
            "then call again with confirm=true."
        ),
    }
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_legacy_snake_case_destructive_tool_also_waits(harness):
    harness.instances = [_instance("Leads", [_tool("delete_lead", destructive_hint=True)])]

    result = await _call(connector="Leads", tool="delete_lead")

    assert result["confirmation_required"] is True
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_confirmed_destructive_tool_runs(harness):
    harness.instances = [_instance("Leads", [_tool("delete_lead", destructiveHint=True)])]

    result = await _call(connector="Leads", tool="delete_lead", confirm=True)

    assert result["content"] == [{"type": "text", "text": "ok"}]
    harness.dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_connector_waiting_on_a_credential_returns_its_connect_link(harness):
    sentry = _instance("Sentry", [_tool("list_issues")], {"status": "failed"})
    harness.instances = [sentry]
    harness.service.needs_connecting = AsyncMock(return_value=True)

    result = await _call(connector="Sentry", tool="list_issues")

    url = f"https://app.example/w/acme/connect/{sentry.id}"
    assert result["action_required"] == {
        "type": "connect",
        "url": url,
        "message": f"Open this link to connect Sentry: {url}",
    }
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_tool_suggests_close_names(harness):
    harness.instances = [
        _instance("A", [_tool("list_campaigns"), _tool("list_leads"), _tool("send_email")])
    ]

    result = await _call(connector="A", tool="list_campaign")

    assert "list_campaign" in result["error"]
    assert result["suggestions"][0] == "list_campaigns"
    assert "send_email" not in result["suggestions"]
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_ambiguous_connector_name_lists_the_ids(harness):
    one = _instance("Mail", [_tool("t")])
    two = _instance("Mail", [_tool("t")])
    harness.instances = [one, two]

    result = await _call(connector="Mail", tool="t")

    assert "ambiguous" in result["error"]
    assert sorted(result["connector_ids"]) == sorted([str(one.id), str(two.id)])
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_connector_is_an_error(harness):
    harness.instances = [_instance("A", [_tool("t")])]

    result = await _call(connector="Nope", tool="t")

    assert "Nope" in result["error"]
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_connector_is_found_by_id(harness):
    one = _instance("Mail", [_tool("t")])
    two = _instance("Mail", [_tool("t")])
    harness.instances = [one, two]

    result = await _call(connector=str(two.id), tool="t")

    assert result["connector_id"] == str(two.id)


@pytest.mark.asyncio
async def test_call_runs_an_openapi_tool_through_the_openapi_dispatch(harness):
    analytics = _connection(
        "Google Analytics Admin",
        [_tool("listAccounts")],
        _operation("/v1/accounts", "get", "listAccounts"),
    )
    harness.connections = [analytics]
    harness.openapi_dispatch.return_value = CallToolResult(
        content=[TextContent(type="text", text='{"accounts": []}')]
    )

    result = await _call(
        connector="Google Analytics Admin", tool="listAccounts", arguments={"pageSize": 5}
    )

    assert result == {
        "connector_id": str(analytics.id),
        "connector": "Google Analytics Admin",
        "tool": "listAccounts",
        "content": [{"type": "text", "text": '{"accounts": []}'}],
    }
    _session, user_ctx, service, connection, tool, arguments = (
        harness.openapi_dispatch.await_args.args
    )
    assert (user_ctx, service, connection, tool, arguments) == (
        CALLER,
        harness.openapi,
        analytics,
        "listAccounts",
        {"pageSize": 5},
    )
    connector_tools_toolset.require_permission.assert_awaited_once_with(
        "use", "openapi_connection", str(analytics.id), CALLER.user_id
    )
    harness.dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_openapi_call_is_reported_as_an_error(harness):
    harness.connections = [_connection("Api", [_tool("t")], _operation("/t", "get", "t"))]
    harness.openapi_dispatch.return_value = CallToolResult(
        content=[TextContent(type="text", text="HTTP 404: missing")], is_error=True
    )

    result = await _call(connector="Api", tool="t")

    assert result["is_error"] is True
    assert result["content"] == [{"type": "text", "text": "HTTP 404: missing"}]


@pytest.mark.asyncio
async def test_a_caller_without_use_on_an_openapi_connection_is_refused(harness):
    harness.connections = [_connection("Api", [_tool("t")])]
    connector_tools_toolset.require_permission.side_effect = HTTPException(
        status_code=403, detail="Permission denied"
    )

    result = await _call(connector="Api", tool="t")

    assert result == {"error": "Permission denied"}
    harness.openapi_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_openapi_delete_waits_for_confirmation(harness):
    harness.connections = [
        _connection(
            "Api", [_tool("deleteAccount")], _operation("/a/{id}", "delete", "deleteAccount")
        )
    ]

    result = await _call(connector="Api", tool="deleteAccount", arguments={"id": "1"})

    assert result["confirmation_required"] is True
    harness.openapi_dispatch.assert_not_awaited()

    confirmed = await _call(connector="Api", tool="deleteAccount", confirm=True)

    assert confirmed["content"] == [{"type": "text", "text": "ok"}]


@pytest.mark.asyncio
async def test_an_unknown_openapi_tool_suggests_close_names(harness):
    harness.connections = [_connection("Api", [_tool("listAccounts"), _tool("getAccount")])]

    result = await _call(connector="Api", tool="listAccount")

    assert result["suggestions"][0] == "listAccounts"
    harness.openapi_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_name_shared_by_an_mcp_and_an_openapi_connector_is_ambiguous(harness):
    mcp = _instance("Mail", [_tool("t")])
    api = _connection("mail", [_tool("t")])
    harness.instances = [mcp]
    harness.connections = [api]

    result = await _call(connector="Mail", tool="t")

    assert "ambiguous" in result["error"]
    assert sorted(result["connector_ids"]) == sorted([str(mcp.id), str(api.id)])
    harness.dispatch.assert_not_awaited()
    harness.openapi_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_openapi_connection_is_found_by_id(harness):
    api = _connection("Api", [_tool("t")])
    harness.connections = [api]

    result = await _call(connector=str(api.id), tool="t")

    assert result["connector_id"] == str(api.id)


@pytest.mark.asyncio
async def test_a_catalog_connection_whose_sign_in_lapsed_returns_its_connect_link(harness):
    from agentarea_mcp.application.auth_service import OAuthReauthRequiredError

    item_id = uuid4()
    api = _connection(
        "Google Analytics Admin",
        [_tool("listAccounts")],
        registry_item_id=item_id,
        auth_config_id=uuid4(),
    )
    harness.connections = [api]
    harness.openapi.resolve_headers.side_effect = OAuthReauthRequiredError("expired")

    result = await _call(connector="Google Analytics Admin", tool="listAccounts")

    url = f"https://app.example/w/acme/connect/catalog/{item_id}"
    assert result["action_required"] == {
        "type": "connect",
        "url": url,
        "message": f"Open this link to connect Google Analytics Admin: {url}",
    }
    assert result["connector_id"] == str(api.id)
    harness.openapi_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_catalog_connection_without_an_auth_config_returns_its_connect_link(harness):
    item_id = uuid4()
    harness.connections = [_connection("Api", [_tool("t")], registry_item_id=item_id)]

    result = await _call(connector="Api", tool="t")

    assert result["action_required"]["url"] == (
        f"https://app.example/w/acme/connect/catalog/{item_id}"
    )
    harness.openapi_dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_signed_in_catalog_connection_runs(harness):
    harness.connections = [
        _connection("Api", [_tool("t")], registry_item_id=uuid4(), auth_config_id=uuid4())
    ]

    result = await _call(connector="Api", tool="t")

    assert result["content"] == [{"type": "text", "text": "ok"}]


# --- the dispatch itself -------------------------------------------------------


class _AuditSession:
    def __init__(self, events: list[AuditEventORM]) -> None:
        self._events = events

    def add(self, event: AuditEventORM) -> None:
        self._events.append(event)

    async def flush(self) -> None:
        return None


@pytest.fixture
def dispatch_env(monkeypatch):
    """The real ``call_instance_tool`` over a stubbed upstream and audit sink."""
    events: list[AuditEventORM] = []

    @asynccontextmanager
    async def session():
        yield _AuditSession(events)

    monkeypatch.setattr(
        "agentarea_common.config.database.get_database", lambda: SimpleNamespace(session=session)
    )
    monkeypatch.setattr(client_mcp, "_tool_cache", lambda: None)
    upstream: list[tuple[str, dict]] = []

    async def call_member(_self, _member, tool_name, arguments):
        upstream.append((tool_name, arguments))
        return CallToolResult(content=[TextContent(type="text", text=f"ran {tool_name}")])

    monkeypatch.setattr(MCPAggregatorProxy, "_call_member_tool_result", call_member)
    instance = SimpleNamespace(id=uuid4(), name="DeepWiki", transport="url")
    service = MagicMock()
    service.repository.get_by_id = AsyncMock(return_value=instance)
    service._resolve_mcp_url_and_headers = AsyncMock(
        return_value=("http://deepwiki.invalid/mcp", {}, None)
    )
    policy: dict = {}

    async def effective(_session, _user_ctx):
        return policy

    monkeypatch.setattr(client_mcp, "_effective_tool_policy", effective)
    return SimpleNamespace(
        events=events, upstream=upstream, instance=instance, service=service, policy=policy
    )


@pytest.mark.asyncio
async def test_dispatch_runs_the_tool_and_audits_it_against_the_connector(dispatch_env):
    env = dispatch_env

    result = await client_mcp.call_instance_tool(
        AsyncMock(), CALLER, env.service, env.instance, "ask_question", {"question": "secret"}
    )

    assert result.content == [TextContent(type="text", text="ran ask_question")]
    assert env.upstream == [("ask_question", {"question": "secret"})]
    [event] = env.events
    assert event.action == "tool.call.allowed"
    assert (event.resource_type, event.resource_id) == ("mcp_instance", str(env.instance.id))
    assert event.actor_type == "user"
    assert event.event_metadata["mcp_instance_id"] == str(env.instance.id)
    assert event.event_metadata["argument_keys"] == ["question"]
    assert "secret" not in str(event.event_metadata)


@pytest.mark.asyncio
async def test_dispatch_refuses_a_tool_the_policy_denies(dispatch_env):
    env = dispatch_env
    env.policy["tools"] = {"denied": ["mcp:DeepWiki:ask_question"]}

    result = await client_mcp.call_instance_tool(
        AsyncMock(), CALLER, env.service, env.instance, "ask_question", {}
    )

    assert result.is_error is True
    assert env.upstream == []
    [event] = env.events
    assert event.action == "tool.call.denied"


@pytest.mark.asyncio
async def test_dispatch_refuses_a_tool_held_for_approval_because_a_call_cannot_wait(dispatch_env):
    env = dispatch_env
    env.policy["approval"] = {"escalation_rules": ["ask_*"]}

    result = await client_mcp.call_instance_tool(
        AsyncMock(), CALLER, env.service, env.instance, "ask_question", {}
    )

    assert result.is_error is True
    assert "cannot wait for approval" in result.content[0].text
    assert env.upstream == []
    [event] = env.events
    assert event.action == "tool.call.denied"
    assert event.event_metadata["decision"] == "require_approval"


@pytest.fixture
def openapi_env(dispatch_env, monkeypatch):
    """The real ``call_openapi_tool`` over the agents' OpenAPI tool, its HTTP call stubbed."""
    from agentarea_agents_sdk.tools.openapi_tool import OpenAPITool

    executed: list[tuple[str, dict]] = []
    outcome: dict[str, Any] = {
        "success": True,
        "result": '{"accounts": []}',
        "error": None,
        "status_code": 200,
    }

    async def execute(self, **kwargs):
        executed.append((self.name, kwargs))
        return {**outcome, "tool_name": self.name}

    monkeypatch.setattr(OpenAPITool, "execute", execute)
    connection = _connection(
        "Google Analytics Admin",
        [_tool("accounts.list")],
        _operation("/v1/accounts", "get", "accounts.list"),
    )
    service = MagicMock()
    service.get_connection = AsyncMock(return_value=connection)
    return SimpleNamespace(
        events=dispatch_env.events,
        policy=dispatch_env.policy,
        executed=executed,
        outcome=outcome,
        connection=connection,
        service=service,
    )


@pytest.mark.asyncio
async def test_openapi_dispatch_runs_the_operation_and_audits_it_against_the_connection(
    openapi_env,
):
    env = openapi_env

    result = await client_mcp.call_openapi_tool(
        AsyncMock(), CALLER, env.service, env.connection, "accounts.list", {"pageSize": 5}
    )

    assert result.content == [TextContent(type="text", text='{"accounts": []}')]
    assert not result.is_error
    assert env.executed == [("accounts_list", {"pageSize": 5})]
    [event] = env.events
    assert event.action == "tool.call.allowed"
    assert (event.resource_type, event.resource_id) == (
        "openapi_connection",
        str(env.connection.id),
    )
    assert event.event_metadata["argument_keys"] == ["pageSize"]


@pytest.mark.asyncio
async def test_openapi_dispatch_reports_a_failed_request_as_an_error(openapi_env):
    env = openapi_env
    env.outcome.update(success=False, result=None, error="HTTP 403: forbidden", status_code=403)

    result = await client_mcp.call_openapi_tool(
        AsyncMock(), CALLER, env.service, env.connection, "accounts.list", {}
    )

    assert result.is_error is True
    assert result.content == [TextContent(type="text", text="HTTP 403: forbidden")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule", ["accounts_list", "accounts.list", "Google Analytics Admin", "connection-id"]
)
async def test_openapi_dispatch_refuses_what_the_policy_denies(openapi_env, rule):
    env = openapi_env
    if rule == "connection-id":
        rule = str(env.connection.id)
    env.policy["tools"] = {"denied": [rule]}

    result = await client_mcp.call_openapi_tool(
        AsyncMock(), CALLER, env.service, env.connection, "accounts.list", {}
    )

    assert result.is_error is True
    assert env.executed == []
    [event] = env.events
    assert event.action == "tool.call.denied"
    assert event.resource_type == "openapi_connection"


@pytest.mark.asyncio
async def test_openapi_dispatch_reports_an_operation_the_spec_lacks(openapi_env):
    env = openapi_env

    result = await client_mcp.call_openapi_tool(
        AsyncMock(), CALLER, env.service, env.connection, "nope", {}
    )

    assert result.is_error is True
    assert env.executed == []
    assert env.events == []
