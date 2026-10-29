"""A client's tool calls answer to the workspace policy and land in the audit trail.

The client endpoint reaches the same upstream an agent does, so a tool the
policy denies must be refused there too, and every verdict recorded — not only
the calls an agent makes. Calls held for approval: test_client_tool_call_approvals.py.
"""

import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from agentarea_api.api.v1 import client_mcp
from agentarea_common.audit import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

# Audit rows are ORM objects, so every registered mapper must resolve — and a
# client's mapper names Skill.
importlib.import_module("agentarea_agents.domain.skill_models")

CLIENT_ID = "33333333-3333-3333-3333-333333333333"
INSTANCE_ID = "44444444-4444-4444-4444-444444444444"


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


class _AuditSession:
    """Captures what the audit service writes."""

    def __init__(self, events: list[AuditEventORM]) -> None:
        self._events = events

    def add(self, event: AuditEventORM) -> None:
        self._events.append(event)

    async def flush(self) -> None:
        return None


@pytest.fixture
def audit_events(monkeypatch) -> list[AuditEventORM]:
    events: list[AuditEventORM] = []

    @asynccontextmanager
    async def session():
        yield _AuditSession(events)

    monkeypatch.setattr(
        "agentarea_common.config.database.get_database", lambda: SimpleNamespace(session=session)
    )
    return events


@pytest.fixture
def upstream_calls() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
def client(monkeypatch, upstream_calls):
    """A client carrying one DeepWiki instance, under a policy each test sets."""
    proxy = MCPAggregatorProxy(
        "Codex",
        "",
        [AggregatedMember(mcp_instance_id=INSTANCE_ID, pinned=False)],
        {INSTANCE_ID: "http://deepwiki.invalid/mcp"},
        {INSTANCE_ID: "DeepWiki"},
        era_verdict_store=object(),
    )

    async def discover(_member):
        return [
            {"name": "ask_question", "inputSchema": {"type": "object"}},
            {"name": "read_wiki_structure", "inputSchema": {"type": "object"}},
        ]

    async def call_member(_member, tool_name, arguments):
        upstream_calls.append((tool_name, arguments))
        return CallToolResult(content=[TextContent(type="text", text=f"ran {tool_name}")])

    monkeypatch.setattr(proxy, "_discover_member_tools", discover)
    monkeypatch.setattr(proxy, "_call_member_tool_result", call_member)

    def with_policy(policy: dict) -> None:
        scope = client_mcp.ClientScope(
            proxy=proxy,
            skill_registry={},
            platform_tools=frozenset(),
            user_context=UserContext(user_id="user-1", workspace_id="client-ws"),
            tool_policy=policy,
            actor_type="api_key",
        )

        async def resolve(_client_id):
            return scope

        monkeypatch.setattr(client_mcp, "_resolve_client_scope", resolve)

    token = client_mcp._client_id_var.set(CLIENT_ID)
    yield with_policy
    client_mcp._client_id_var.reset(token)


async def _call(name: str, **arguments):
    return await client_mcp._call_tool(None, CallToolRequestParams(name=name, arguments=arguments))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rule",
    [
        f"mcp:{INSTANCE_ID}:ask_question",
        "mcp:DeepWiki:ask_question",
        "mcp__deepwiki__ask_question",
        "ask_question",
    ],
)
async def test_a_policy_denied_tool_is_refused_and_audited(
    client, audit_events, upstream_calls, rule
):
    client({"tools": {"denied": [rule]}})

    result = await _call("deepwiki__ask_question", question="secret question")

    assert result.is_error is True
    assert "denied by policy" in _text(result)
    assert upstream_calls == []
    [event] = audit_events
    assert event.action == "tool.call.denied"
    assert (event.resource_type, event.resource_id) == ("client", CLIENT_ID)
    assert event.workspace_id == "client-ws"
    assert event.actor_type == "api_key"
    assert event.event_metadata["tool"] == "deepwiki__ask_question"
    assert event.event_metadata["mcp_instance_id"] == INSTANCE_ID


@pytest.mark.asyncio
async def test_an_allowlist_naming_the_bare_tool_admits_no_server(
    client, audit_events, upstream_calls
):
    client({"tools": {"allowed": ["ask_question"]}})

    result = await _call("deepwiki__ask_question", question="q")

    assert result.is_error is True
    assert "allowlist" in _text(result)
    assert upstream_calls == []


@pytest.mark.asyncio
async def test_an_allowlist_naming_the_servers_tool_admits_it(
    client, audit_events, upstream_calls
):
    client({"tools": {"allowed": [f"mcp:{INSTANCE_ID}:ask_question"]}})

    result = await _call("deepwiki__ask_question", question="q")

    assert result.is_error is not True
    assert upstream_calls == [("ask_question", {"question": "q"})]


@pytest.mark.asyncio
async def test_a_denied_tool_is_not_offered(client):
    client({"tools": {"denied": ["ask_question"]}})

    listed = await client_mcp._list_tools(None, None)

    assert [tool.name for tool in listed.tools] == ["deepwiki__read_wiki_structure"]


@pytest.mark.asyncio
async def test_an_allowed_tool_runs_and_is_audited_without_argument_values(
    client, audit_events, upstream_calls
):
    client({"tools": {"denied": ["ask_question"]}})

    result = await _call("deepwiki__read_wiki_structure", repoName="secret/repo")

    assert result.content == [TextContent(type="text", text="ran read_wiki_structure")]
    assert upstream_calls == [("read_wiki_structure", {"repoName": "secret/repo"})]
    [event] = audit_events
    assert event.action == "tool.call.allowed"
    assert event.event_metadata["argument_keys"] == ["repoName"]
    assert "secret/repo" not in str(event.event_metadata)


class _Ledger:
    def __init__(self) -> None:
        self.entries: list = []

    def __call__(self, session, user_context):
        return self

    async def record(self, entries) -> None:
        self.entries.extend(entries)


class _Billing:
    """Billing as the layer asks it: a hold of 0.64 EUR per platform call, or no credits."""

    def __init__(self, allow: bool) -> None:
        self.allow = allow

    def currency(self) -> str:
        return "EUR"

    async def authorize(self, **request):
        from decimal import Decimal

        return SimpleNamespace(
            allowed=self.allow,
            code="ok" if self.allow else "no_credits",
            reason="" if self.allow else "no credits remaining",
            hold_id="hold-1" if self.allow else None,
            amount=Decimal("0.64") if self.allow else None,
            currency="EUR" if self.allow else None,
            expires_at=None,
        )

    async def void(self, *, hold_id):
        return None

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def quote(self, lines):
        raise AssertionError("every cost here is in the deployment currency")


@pytest.fixture
def paid_client(monkeypatch, audit_events, upstream_calls):
    """A client carrying the platform's tool-gateway, priced, its ledger captured."""
    from decimal import Decimal

    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry
    from agentarea_tasks.infrastructure import cost_repository

    proxy = MCPAggregatorProxy(
        "Codex",
        "",
        [AggregatedMember(mcp_instance_id=INSTANCE_ID, pinned=False)],
        {INSTANCE_ID: "http://tools.invalid/mcp"},
        {INSTANCE_ID: "Tools"},
        era_verdict_store=object(),
    )
    gateway = SimpleNamespace(id=INSTANCE_ID, managed_by="platform", server_spec_id="spec")
    catalog_entry = {
        "name": "example.com/search-api",
        "metadata": {
            "agentarea:payers": ["platform"],
            "agentarea:cost": {
                "default": {"source": "rate", "rate": {"amount": "0.488", "currency": "EUR"}}
            },
        },
    }

    async def server_spec(_user_ctx, instance):
        assert instance is gateway
        return catalog_entry

    monkeypatch.setattr(client_mcp, "_catalog_server_spec", server_spec)

    async def discover(_member):
        return [{"name": "example_search", "inputSchema": {"type": "object"}}]

    async def call_member(_member, tool_name, arguments):
        upstream_calls.append((tool_name, arguments))
        return CallToolResult(content=[TextContent(type="text", text="[]")])

    monkeypatch.setattr(proxy, "_discover_member_tools", discover)
    monkeypatch.setattr(proxy, "_call_member_tool_result", call_member)
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    ledger = _Ledger()
    monkeypatch.setattr(cost_repository, "CostEntryRepository", ledger)
    scope = client_mcp.ClientScope(
        proxy=proxy,
        skill_registry={},
        platform_tools=frozenset(),
        user_context=UserContext(user_id="user-1", workspace_id="client-ws"),
        tool_policy={},
        actor_type="client",
        client_id=CLIENT_ID,
        instances={INSTANCE_ID: gateway},
    )

    async def resolve(_client_id):
        return scope

    monkeypatch.setattr(client_mcp, "_resolve_client_scope", resolve)
    token = client_mcp._client_id_var.set(CLIENT_ID)

    def with_balance(allow: bool) -> _Ledger:
        ExtensionRegistry.clear()
        tool_billing.get_tool_billing.cache_clear()
        ExtensionRegistry.register("tool_billing", lambda: _Billing(allow))
        return ledger

    yield with_balance
    client_mcp._client_id_var.reset(token)
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


@pytest.mark.asyncio
async def test_a_paid_client_call_is_one_ledger_line_of_the_client_and_no_task(
    paid_client, upstream_calls
):
    from decimal import Decimal
    from uuid import UUID

    ledger = paid_client(True)

    result = await _call("tools__example_search", query="agentarea")

    assert result.is_error is not True
    assert upstream_calls == [("example_search", {"query": "agentarea"})]
    [entry] = ledger.entries
    assert (entry.task_id, entry.agent_id, entry.client_id) == (None, None, UUID(CLIENT_ID))
    assert (entry.workspace_id, entry.created_by) == ("client-ws", "user-1")
    assert (entry.subject_id, entry.subject_name, entry.payer.value) == (
        INSTANCE_ID,
        "example_search",
        "platform",
    )
    assert (entry.vendor_cost, entry.vendor_currency, entry.amount, entry.currency) == (
        Decimal("0.488"),
        "EUR",
        Decimal("0.64"),
        "EUR",
    )
    assert entry.evidence["connector"] == "example.com/search-api"


@pytest.mark.asyncio
async def test_a_client_with_no_balance_is_refused_before_the_gateway_is_called(
    paid_client, upstream_calls, audit_events
):
    ledger = paid_client(False)

    result = await _call("tools__example_search", query="agentarea")

    assert result.is_error is True
    assert "no credits remaining" in _text(result)
    assert upstream_calls == [] and ledger.entries == []
    [event] = audit_events
    assert event.action == "tool.call.denied"


CONNECTION_ID = "55555555-5555-5555-5555-555555555555"


def _example_connection():
    from uuid import UUID

    return SimpleNamespace(
        id=UUID(CONNECTION_ID),
        name="Example Search",
        managed_by="platform",
        available_tools=[
            {
                "name": "search",
                "description": "Web search",
                "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
            },
            {"name": "wordstat", "description": "Phrase stats", "inputSchema": {"type": "object"}},
        ],
        spec_content={
            "openapi": "3.0.0",
            "x-agentarea-payers": ["platform"],
            "x-agentarea-cost": {"source": "rate", "rate": {"amount": "0.488", "currency": "EUR"}},
            "paths": {
                "/search": {"post": {"operationId": "search", "summary": "Web search"}},
                "/wordstat": {"post": {"operationId": "wordstat", "summary": "Phrase stats"}},
            },
        },
        custom_query_params=[],
        registry_item_id=None,
        auth_config_id=None,
    )


@pytest.fixture
def openapi_client(monkeypatch, audit_events):
    """A client carrying the platform's Example OpenAPI connection, its ledger captured."""
    from decimal import Decimal
    from unittest.mock import AsyncMock, MagicMock

    from agentarea_agents_sdk.tools.openapi_tool import OpenAPITool
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry
    from agentarea_mcp.domain.client_models import ClientOpenAPIConnectionLink
    from agentarea_tasks.infrastructure import cost_repository

    connection = _example_connection()
    service = MagicMock()
    service.get_connection = AsyncMock(return_value=connection)
    service.catalog_connector = AsyncMock(return_value="example.com/search-api")
    service.catalog_spec = AsyncMock(return_value=connection.spec_content)

    @asynccontextmanager
    async def connection_service(_user_ctx):
        yield service

    monkeypatch.setattr(client_mcp, "_openapi_connection_service", connection_service)
    executed: list[tuple[str, dict]] = []

    async def execute(self, **kwargs):
        executed.append((self.name, kwargs))
        return {"success": True, "result": "[]", "error": None, "status_code": 200, "body": []}

    monkeypatch.setattr(OpenAPITool, "execute", execute)
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    ledger = _Ledger()
    monkeypatch.setattr(cost_repository, "CostEntryRepository", ledger)
    link = ClientOpenAPIConnectionLink(
        connection_id=CONNECTION_ID, name="Example Search", namespace_prefix=None, allowed_tools=None
    )
    state = SimpleNamespace(ledger=ledger, executed=executed, policy={}, link=link)

    def with_scope(*, balance: bool = True, policy: dict | None = None):
        ExtensionRegistry.clear()
        tool_billing.get_tool_billing.cache_clear()
        ExtensionRegistry.register("tool_billing", lambda: _Billing(balance))
        scope = client_mcp.ClientScope(
            proxy=MCPAggregatorProxy("Codex", "", [], {}, {}, era_verdict_store=object()),
            skill_registry={},
            platform_tools=frozenset(),
            user_context=UserContext(user_id="user-1", workspace_id="client-ws"),
            tool_policy=policy or {},
            actor_type="client",
            client_id=CLIENT_ID,
            openapi=client_mcp.client_openapi_operations([state.link], [connection]),
        )

        async def resolve(_client_id):
            return scope

        monkeypatch.setattr(client_mcp, "_resolve_client_scope", resolve)
        return state

    token = client_mcp._client_id_var.set(CLIENT_ID)
    yield with_scope
    client_mcp._client_id_var.reset(token)
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


@pytest.mark.asyncio
async def test_a_client_lists_the_operations_of_its_openapi_connection(openapi_client):
    from agentarea_mcp.domain.client_models import ClientOpenAPIConnectionLink

    state = openapi_client()
    listed = await client_mcp._list_tools(None, None)
    assert [tool.name for tool in listed.tools] == [
        "example_search__search",
        "example_search__wordstat",
    ]
    assert listed.tools[0].description == "Web search"

    state.link = ClientOpenAPIConnectionLink(
        connection_id=CONNECTION_ID,
        name="Example Search",
        namespace_prefix="ya",
        allowed_tools=["wordstat"],
    )
    openapi_client(policy={"tools": {"denied": ["search"]}})
    listed = await client_mcp._list_tools(None, None)
    assert [tool.name for tool in listed.tools] == ["ya__wordstat"]


@pytest.mark.asyncio
async def test_a_client_call_of_a_platform_openapi_operation_is_one_ledger_line_of_the_client(
    openapi_client, audit_events
):
    from decimal import Decimal
    from uuid import UUID

    state = openapi_client()

    result = await _call("example_search__search", query="agentarea")

    assert result.is_error is not True
    assert state.executed == [("search", {"query": "agentarea"})]
    [entry] = state.ledger.entries
    assert (entry.task_id, entry.agent_id, entry.client_id) == (None, None, UUID(CLIENT_ID))
    assert (entry.subject_id, entry.subject_name, entry.payer.value) == (
        CONNECTION_ID,
        "search",
        "platform",
    )
    assert (entry.vendor_cost, entry.vendor_currency, entry.amount, entry.currency) == (
        Decimal("0.488"),
        "EUR",
        Decimal("0.64"),
        "EUR",
    )
    assert entry.evidence["connector"] == "example.com/search-api"
    [event] = audit_events
    assert event.action == "tool.call.allowed"
    assert (event.resource_type, event.resource_id) == ("client", CLIENT_ID)
    assert event.event_metadata["openapi_connection_id"] == CONNECTION_ID


@pytest.mark.asyncio
async def test_a_client_openapi_call_without_balance_is_refused_before_the_vendor(
    openapi_client, audit_events
):
    state = openapi_client(balance=False)

    result = await _call("example_search__search", query="agentarea")

    assert result.is_error is True
    assert "no credits remaining" in _text(result)
    assert state.executed == [] and state.ledger.entries == []
    [event] = audit_events
    assert event.action == "tool.call.denied"


@pytest.mark.asyncio
@pytest.mark.parametrize("rule", ["search", "Example Search", CONNECTION_ID])
async def test_a_client_openapi_call_the_policy_denies_never_reaches_the_vendor(
    openapi_client, audit_events, rule
):
    state = openapi_client(policy={"tools": {"denied": [rule]}})

    result = await _call("example_search__search", query="agentarea")

    assert result.is_error is True
    assert "denied by policy" in _text(result)
    assert state.executed == [] and state.ledger.entries == []
