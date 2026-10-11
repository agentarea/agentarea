"""Approval links on the client surfaces: ``/mcp/clients/{id}`` and ``tools_call``.

A client call the workspace policy holds for approval used to be refused, since
a stateless request cannot wait. It now records the exact call and answers with
a link: a person approves it in the browser, and the client's retry with the
same arguments runs it once. The decision endpoints are what that page calls.
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
from agentarea_api.api.v1 import client_mcp, tool_call_approvals
from agentarea_api.tools import connector_tools_toolset
from agentarea_api.tools.connector_tools_toolset import ConnectorToolsToolset
from agentarea_common.audit import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application.tool_call_approvals import ToolCallApprovalService
from agentarea_governance.domain.tool_call_approvals import ToolCallApprovalStatus
from agentarea_governance.infrastructure.orm import ToolCallApprovalORM
from agentarea_mcp.application.mcp_aggregator import AggregatedMember, MCPAggregatorProxy
from fastapi import HTTPException
from mcp.types import CallToolRequestParams, CallToolResult, TextContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

importlib.import_module("agentarea_agents.domain.skill_models")

CLIENT_ID = "3c9a1f2e-5b4d-4e6f-8a7b-9c0d1e2f3a4b"
INSTANCE_ID = "4f1c2a9e-7b3d-4c5e-9a8b-1d2e3f4a5b6c"
WORKSPACE = "ws-acme"
REQUESTER = UserContext(user_id="user-1", workspace_id=WORKSPACE, workspace_slug="acme")
APPROVER = UserContext(user_id="user-2", workspace_id=WORKSPACE, workspace_slug="acme")
GATED = {"approval": {"escalation_rules": ["ask_*"]}}


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


@pytest.fixture
async def db(monkeypatch):
    """Approvals and the audit trail on SQLite, behind ``get_database().session()``."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=[ToolCallApprovalORM.__table__, AuditEventORM.__table__]
            )
        )
    sessions = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    @asynccontextmanager
    async def session():
        async with sessions() as s:
            yield s
            await s.commit()

    monkeypatch.setattr(
        "agentarea_common.config.database.get_database", lambda: SimpleNamespace(session=session)
    )
    monkeypatch.setattr(
        tool_call_approvals,
        "get_settings",
        lambda: SimpleNamespace(app=SimpleNamespace(FRONTEND_BASE_URL="https://app.example/")),
    )
    yield session
    await engine.dispose()


async def _approvals(db) -> list[ToolCallApprovalORM]:
    async with db() as s:
        return list((await s.scalars(select(ToolCallApprovalORM))).all())


async def _audit(db) -> list[AuditEventORM]:
    async with db() as s:
        return list(
            (
                await s.scalars(
                    select(AuditEventORM)
                    .where(AuditEventORM.action.like("tool.call.%"))
                    .order_by(AuditEventORM.created_at)
                )
            ).all()
        )


async def _decide(db, approval_id: str, approved: bool, comment: str | None = None):
    async with db() as s:
        return await ToolCallApprovalService(RepositoryFactory(s, APPROVER)).decide(
            approval_id, approved=approved, comment=comment
        )


def _url(approval_id: str) -> str:
    return f"https://app.example/w/acme/approve/{approval_id}"


# --- /mcp/clients/{id} -----------------------------------------------------------


@pytest.fixture
def upstream_calls() -> list[tuple[str, dict[str, Any]]]:
    return []


@pytest.fixture
def client(monkeypatch, upstream_calls):
    proxy = MCPAggregatorProxy(
        "Claude Code",
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

    def with_policy(policy: dict, user: UserContext = REQUESTER) -> None:
        scope = client_mcp.ClientScope(
            proxy=proxy,
            skill_registry={},
            platform_tools=frozenset(),
            user_context=user,
            tool_policy=policy,
            actor_type="user",
            client_id=CLIENT_ID,
            client_name="Claude Code",
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
async def test_a_held_call_records_the_exact_call_and_answers_with_its_link(
    client, db, upstream_calls
):
    client(GATED)

    result = await _call("deepwiki__ask_question", question="what is it")

    assert result.is_error is True
    assert upstream_calls == []
    [row] = await _approvals(db)
    assert row.status == "pending"
    assert row.created_by == "user-1"
    assert row.client_id == CLIENT_ID
    assert row.client_name == "Claude Code"
    assert str(row.mcp_instance_id) == INSTANCE_ID
    assert (row.connector, row.tool) == ("DeepWiki", "ask_question")
    assert row.policy_name == "deepwiki__ask_question"
    assert row.arguments == {"question": "what is it"}
    assert "requires approval" in row.reason
    text = _text(result)
    assert _url(str(row.id)) in text
    assert "Ask the user to open the link and approve; then call again with the same arguments" in (
        text
    )
    [event] = await _audit(db)
    assert event.action == "tool.call.denied"
    assert event.event_metadata["decision"] == "require_approval"
    assert event.event_metadata["approval_id"] == str(row.id)
    assert "what is it" not in str(event.event_metadata)


@pytest.mark.asyncio
async def test_a_retry_while_pending_points_at_the_same_approval(client, db):
    client(GATED)

    first = await _call("deepwiki__ask_question", question="q")
    second = await _call("deepwiki__ask_question", question="q")

    [row] = await _approvals(db)
    assert _url(str(row.id)) in _text(first)
    assert _url(str(row.id)) in _text(second)


@pytest.mark.asyncio
async def test_after_approval_the_retry_runs_once_and_the_next_needs_a_new_one(
    client, db, upstream_calls
):
    client(GATED)
    await _call("deepwiki__ask_question", question="q")
    [row] = await _approvals(db)
    await _decide(db, str(row.id), approved=True)

    ran = await _call("deepwiki__ask_question", question="q")

    assert ran.is_error is not True
    assert _text(ran) == "ran ask_question"
    assert upstream_calls == [("ask_question", {"question": "q"})]
    allowed = [e for e in await _audit(db) if e.action == "tool.call.allowed"]
    assert [e.event_metadata["approval_id"] for e in allowed] == [str(row.id)]

    again = await _call("deepwiki__ask_question", question="q")

    assert again.is_error is True
    assert upstream_calls == [("ask_question", {"question": "q"})]
    rows = await _approvals(db)
    assert sorted(r.status for r in rows) == ["consumed", "pending"]
    [fresh] = [r for r in rows if r.status == "pending"]
    assert _url(str(fresh.id)) in _text(again)


@pytest.mark.asyncio
async def test_an_approval_does_not_run_other_arguments_or_another_user(
    client, db, upstream_calls
):
    client(GATED)
    await _call("deepwiki__ask_question", question="q")
    [row] = await _approvals(db)
    await _decide(db, str(row.id), approved=True)

    changed = await _call("deepwiki__ask_question", question="other")
    client(GATED, user=APPROVER)
    someone_else = await _call("deepwiki__ask_question", question="q")

    assert changed.is_error is True
    assert someone_else.is_error is True
    assert upstream_calls == []


@pytest.mark.asyncio
async def test_a_rejected_call_is_answered_with_the_rejection(client, db, upstream_calls):
    client(GATED)
    await _call("deepwiki__ask_question", question="q")
    [row] = await _approvals(db)
    await _decide(db, str(row.id), approved=False, comment="not this repo")

    retry = await _call("deepwiki__ask_question", question="q")

    assert retry.is_error is True
    assert "the user rejected this call" in _text(retry)
    assert "not this repo" in _text(retry)
    assert upstream_calls == []
    assert len(await _approvals(db)) == 1


@pytest.mark.asyncio
async def test_a_denied_tool_is_still_a_plain_refusal(client, db):
    client({"tools": {"denied": ["ask_question"]}})

    result = await _call("deepwiki__ask_question", question="q")

    assert result.is_error is True
    assert "denied by policy" in _text(result)
    assert await _approvals(db) == []


@pytest.mark.asyncio
async def test_an_approval_gated_tool_is_offered(client):
    client(GATED)

    listed = await client_mcp._list_tools(None, None)

    assert sorted(tool.name for tool in listed.tools) == [
        "deepwiki__ask_question",
        "deepwiki__read_wiki_structure",
    ]


@pytest.mark.asyncio
async def test_the_approvers_the_policy_names_are_kept_on_the_approval(client, db):
    client(
        {
            "approval": {
                "escalation_rules": ["ask_*"],
                "approvers_by_tool": {"ask_*": ["user:user-2"]},
            }
        }
    )

    await _call("deepwiki__ask_question", question="q")

    [row] = await _approvals(db)
    assert row.approvers == ["user:user-2"]


# --- tools_call -----------------------------------------------------------------


@pytest.fixture
def dispatch(monkeypatch):
    """The real ``call_instance_tool`` over a stubbed upstream."""
    monkeypatch.setattr(client_mcp, "_tool_cache", lambda: None)
    upstream: list[tuple[str, dict]] = []

    async def call_member(_self, _member, tool_name, arguments):
        upstream.append((tool_name, arguments))
        return CallToolResult(content=[TextContent(type="text", text=f"ran {tool_name}")])

    monkeypatch.setattr(MCPAggregatorProxy, "_call_member_tool_result", call_member)
    instance = SimpleNamespace(id=INSTANCE_ID, name="DeepWiki", transport="url")
    service = MagicMock()
    service.repository.get_by_id = AsyncMock(return_value=instance)
    service._resolve_mcp_url_and_headers = AsyncMock(
        return_value=("http://deepwiki.invalid/mcp", {}, None)
    )

    async def effective(_session, _user_ctx):
        return GATED

    monkeypatch.setattr(client_mcp, "_effective_tool_policy", effective)
    return SimpleNamespace(upstream=upstream, instance=instance, service=service)


@pytest.mark.asyncio
async def test_the_dispatch_answers_a_held_call_with_the_approval_to_ask_for(db, dispatch):
    held = await client_mcp.call_instance_tool(
        AsyncMock(), REQUESTER, dispatch.service, dispatch.instance, "ask_question", {"q": 1}
    )

    [row] = await _approvals(db)
    assert isinstance(held, client_mcp.ApprovalRequired)
    assert held == client_mcp.ApprovalRequired(
        approval_id=str(row.id),
        url=_url(str(row.id)),
        message=held.message,
    )
    assert "call again with the same arguments" in held.message
    assert row.client_id is None
    assert dispatch.upstream == []

    await _decide(db, str(row.id), approved=True)
    ran = await client_mcp.call_instance_tool(
        AsyncMock(), REQUESTER, dispatch.service, dispatch.instance, "ask_question", {"q": 1}
    )

    assert isinstance(ran, CallToolResult)
    assert dispatch.upstream == [("ask_question", {"q": 1})]


@pytest.mark.asyncio
async def test_tools_call_hands_the_approval_link_to_the_agent(monkeypatch):
    @asynccontextmanager
    async def _ctx():
        yield AsyncMock(), REQUESTER, MagicMock(), AsyncMock(), AsyncMock()

    monkeypatch.setattr(connector_tools_toolset, "platform_context", _ctx)
    service = MagicMock()
    service.needs_connecting = AsyncMock(return_value=False)
    instance = SimpleNamespace(
        id=uuid4(),
        name="Instantly",
        verification={"status": "succeeded"},
        tools=[{"name": "create_campaign", "inputSchema": {"type": "object"}}],
    )

    async def _list():
        return [instance]

    service.list = _list
    monkeypatch.setattr(mcp_service, "MCPServerInstanceService", lambda **_kwargs: service)
    openapi = MagicMock()
    openapi.list_connections = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(
        connector_tools_toolset, "get_openapi_connection_service", AsyncMock(return_value=openapi)
    )
    monkeypatch.setattr(connector_tools_toolset, "require_permission", AsyncMock())
    held = client_mcp.ApprovalRequired(
        approval_id="a-1", url="https://app.example/w/acme/approve/a-1", message="Ask the user"
    )
    monkeypatch.setattr(client_mcp, "call_instance_tool", AsyncMock(return_value=held))

    with use_mcp_user_context(REQUESTER):
        result = json.loads(
            await ConnectorToolsToolset().call(
                connector="Instantly", tool="create_campaign", arguments={"name": "Q4"}
            )
        )

    assert result == {
        "approval_required": {
            "approval_id": "a-1",
            "url": "https://app.example/w/acme/approve/a-1",
            "message": "Ask the user",
        },
        "connector": "Instantly",
        "tool": "create_campaign",
    }


# --- the decision API -------------------------------------------------------------


async def _pending(db, approvers: list[str] | None = None) -> str:
    from agentarea_governance.domain.tool_call_approvals import ToolCallRequest

    async with db() as s:
        outcome = await ToolCallApprovalService(RepositoryFactory(s, REQUESTER)).gate(
            ToolCallRequest(
                mcp_instance_id=INSTANCE_ID,
                connector="Instantly",
                tool="create_campaign",
                policy_name="instantly__create_campaign",
                arguments={"name": "Q4"},
                reason="tool 'instantly__create_campaign' requires approval",
                approvers=approvers or [],
                client_id=None,
                client_name=None,
            )
        )
    return outcome.approval.id


@pytest.fixture
def no_hint(monkeypatch):
    async def hint(_factory, _approval):
        return None

    monkeypatch.setattr(tool_call_approvals, "_tool_hint", hint)


@pytest.mark.asyncio
async def test_an_approver_sees_the_exact_call_and_can_decide(db, no_hint):
    approval_id = await _pending(db, ["user:user-2"])

    async with db() as s:
        seen = await tool_call_approvals.get_tool_call_approval(
            approval_id, APPROVER, RepositoryFactory(s, APPROVER)
        )

    assert seen.can_decide is True
    assert seen.arguments == {"name": "Q4"}
    assert seen.status is ToolCallApprovalStatus.PENDING
    assert seen.requested_by == "user-1"
    assert seen.url == _url(approval_id)


@pytest.mark.asyncio
async def test_a_member_who_is_neither_approver_nor_requester_sees_no_arguments(db, no_hint):
    approval_id = await _pending(db, ["user:user-2"])
    other = UserContext(user_id="user-3", workspace_id=WORKSPACE, workspace_slug="acme")

    async with db() as s:
        seen = await tool_call_approvals.get_tool_call_approval(
            approval_id, other, RepositoryFactory(s, other)
        )
        with pytest.raises(HTTPException) as refused:
            await tool_call_approvals.decide_tool_call_approval(
                approval_id,
                tool_call_approvals.ToolCallApprovalDecision(approved=True),
                other,
                RepositoryFactory(s, other),
            )

    assert seen.can_decide is False
    assert seen.arguments is None
    assert refused.value.status_code == 403


@pytest.mark.asyncio
async def test_a_decided_approval_cannot_be_decided_again(db, no_hint):
    approval_id = await _pending(db)
    decision = tool_call_approvals.ToolCallApprovalDecision(approved=True, comment="go")

    async with db() as s:
        decided = await tool_call_approvals.decide_tool_call_approval(
            approval_id, decision, APPROVER, RepositoryFactory(s, APPROVER)
        )
    async with db() as s:
        with pytest.raises(HTTPException) as again:
            await tool_call_approvals.decide_tool_call_approval(
                approval_id, decision, APPROVER, RepositoryFactory(s, APPROVER)
            )

    assert decided.status is ToolCallApprovalStatus.APPROVED
    assert decided.comment == "go"
    assert again.value.status_code == 409


@pytest.mark.asyncio
async def test_an_unknown_approval_is_not_found(db, no_hint):
    async with db() as s:
        with pytest.raises(HTTPException) as missing:
            await tool_call_approvals.get_tool_call_approval(
                str(uuid4()), APPROVER, RepositoryFactory(s, APPROVER)
            )
    assert missing.value.status_code == 404


@pytest.mark.asyncio
async def test_pending_approvals_are_listed_for_the_inbox(db, no_hint):
    await _pending(db)

    async with db() as s:
        listed = await tool_call_approvals.list_tool_call_approvals(
            APPROVER, RepositoryFactory(s, APPROVER), status=ToolCallApprovalStatus.PENDING
        )

    assert listed.total == 1
    [item] = listed.items
    assert (item.connector, item.tool) == ("Instantly", "create_campaign")
