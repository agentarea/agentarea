"""A client's tool calls answer to the workspace policy and land in the audit trail.

The client endpoint reaches the same upstream an agent does, so a tool the
policy denies (or holds for approval) must be refused there too, and every
verdict recorded — not only the calls an agent makes.
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
        return f"ran {tool_name}"

    monkeypatch.setattr(proxy, "_discover_member_tools", discover)
    monkeypatch.setattr(proxy, "_call_member_tool", call_member)

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


@pytest.mark.asyncio
async def test_an_approval_gated_tool_is_refused_because_a_client_cannot_wait(
    client, audit_events, upstream_calls
):
    client({"approval": {"escalation_rules": ["ask_*"]}})

    result = await _call("deepwiki__ask_question", question="q")

    assert result.is_error is True
    assert "requires approval" in _text(result)
    assert upstream_calls == []
    [event] = audit_events
    assert event.action == "tool.call.denied"
    assert event.event_metadata["decision"] == "require_approval"
    listed = await client_mcp._list_tools(None, None)
    assert [tool.name for tool in listed.tools] == ["deepwiki__read_wiki_structure"]
