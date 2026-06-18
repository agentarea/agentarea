"""Tests for semantic tool access endpoints."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.v1 import tool_access
from agentarea_api.api.v1.tool_access import (
    ToolAccessCheckRequest,
    ToolAccessGrantRequest,
    check_tool_access,
    grant_tool_access,
)
from agentarea_common.rebac.models import CheckResult
from fastapi import HTTPException


class FakeGraph:
    def __init__(self) -> None:
        self.write_tuple = AsyncMock()
        self.query_all_tuples = AsyncMock(return_value=[])
        self.check = AsyncMock(return_value=CheckResult(allowed=True))


class _EmptyScalarResult:
    def scalar_one_or_none(self):
        return None


class _NoMembershipSession:
    async def execute(self, _query):
        return _EmptyScalarResult()


@pytest.mark.asyncio
async def test_grant_whole_tool_writes_semantic_tool_relationship(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())
    monkeypatch.setattr(tool_access, "_assert_user_in_workspace", AsyncMock())

    response = await grant_tool_access(
        ToolAccessGrantRequest(user_id="u1", tool_name="github.create_issue"),
        SimpleNamespace(workspace_id="ws1"),
        SimpleNamespace(),
    )

    assert response.grant.scope == "tool"
    assert response.grant.workspace_id == "ws1"
    relationship = graph.write_tuple.await_args.args[0]
    assert relationship.namespace == "Tool"
    assert relationship.object == "ws1/github.create_issue"
    assert relationship.relation == "callers"
    assert relationship.subject_id == "User:u1"


@pytest.mark.asyncio
async def test_grant_exact_arguments_writes_tool_resource_relationship(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())
    monkeypatch.setattr(tool_access, "_assert_user_in_workspace", AsyncMock())

    response = await grant_tool_access(
        ToolAccessGrantRequest(
            user_id="u1",
            tool_name="github.create_issue",
            arguments={"repo": "acme/app"},
        ),
        SimpleNamespace(workspace_id="ws1"),
        SimpleNamespace(),
    )

    assert response.grant.scope == "arguments"
    assert response.grant.workspace_id == "ws1"
    relationship = graph.write_tuple.await_args.args[0]
    assert relationship.namespace == "ToolResource"
    assert relationship.object.startswith("ws1/github.create_issue~args~")
    assert relationship.relation == "callers"
    assert relationship.subject_id == "User:u1"


@pytest.mark.asyncio
async def test_grant_rejects_user_outside_workspace(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())

    with pytest.raises(HTTPException) as exc:
        await grant_tool_access(
            ToolAccessGrantRequest(user_id="external-user", tool_name="github.create_issue"),
            SimpleNamespace(user_id="admin-user", workspace_id="ws1"),
            _NoMembershipSession(),
        )

    assert exc.value.status_code == 403
    graph.write_tuple.assert_not_called()


@pytest.mark.asyncio
async def test_check_whole_tool_uses_tool_can_call(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())
    monkeypatch.setattr(tool_access, "_assert_user_in_workspace", AsyncMock())

    response = await check_tool_access(
        ToolAccessCheckRequest(user_id="u1", tool_name="github.create_issue"),
        SimpleNamespace(workspace_id="ws1"),
        SimpleNamespace(),
    )

    assert response.allowed is True
    graph.check.assert_awaited_once_with(
        namespace="Tool",
        object="ws1/github.create_issue",
        relation="can_call",
        subject_id="User:u1",
        contextual_tuples=[
            tool_access.workspace_member_tuple("ws1", "u1"),
            tool_access.tool_workspace_tuple("github.create_issue", "ws1"),
        ],
    )


@pytest.mark.asyncio
async def test_check_exact_arguments_uses_runtime_invocation_helper(monkeypatch):
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: FakeGraph())
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())
    monkeypatch.setattr(tool_access, "_assert_user_in_workspace", AsyncMock())
    helper = AsyncMock(return_value=True)
    monkeypatch.setattr(tool_access, "is_tool_invocation_allowed", helper)

    response = await check_tool_access(
        ToolAccessCheckRequest(
            user_id="u1",
            tool_name="github.create_issue",
            arguments={"repo": "acme/app"},
        ),
        SimpleNamespace(workspace_id="ws1"),
        SimpleNamespace(),
    )

    assert response.allowed is True
    helper.assert_awaited_once()
    assert helper.await_args.kwargs["user_id"] == "u1"
    assert helper.await_args.kwargs["workspace_id"] == "ws1"
    assert helper.await_args.kwargs["tool_name"] == "github.create_issue"
    assert helper.await_args.kwargs["tool_args"] == {"repo": "acme/app"}


@pytest.mark.asyncio
async def test_list_grants_filters_to_current_workspace(monkeypatch):
    from agentarea_common.rebac.models import RelationTuple

    graph = FakeGraph()
    graph.query_all_tuples.side_effect = [
        [
            RelationTuple(
                namespace="Tool",
                object="ws1/github.create_issue",
                relation="callers",
                subject_id="User:u1",
            ),
            RelationTuple(
                namespace="Tool",
                object="ws2/github.create_issue",
                relation="callers",
                subject_id="User:u2",
            ),
        ],
        [
            RelationTuple(
                namespace="ToolResource",
                object="ws1/github.create_issue~args~abc",
                relation="callers",
                subject_id="User:u3",
            )
        ],
    ]
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())

    response = await tool_access.list_tool_access_grants(
        SimpleNamespace(workspace_id="ws1"),
        SimpleNamespace(),
    )

    assert response.count == 2
    assert {grant.workspace_id for grant in response.grants} == {"ws1"}
    assert {grant.user_id for grant in response.grants} == {"u1", "u3"}
