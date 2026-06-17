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


class FakeGraph:
    def __init__(self) -> None:
        self.write_tuple = AsyncMock()
        self.check = AsyncMock(return_value=CheckResult(allowed=True))


@pytest.mark.asyncio
async def test_grant_whole_tool_writes_semantic_tool_relationship(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())

    response = await grant_tool_access(
        ToolAccessGrantRequest(user_id="u1", tool_name="github.create_issue"),
        SimpleNamespace(workspace_id="ws1"),
    )

    assert response.grant.scope == "tool"
    relationship = graph.write_tuple.await_args.args[0]
    assert relationship.namespace == "Tool"
    assert relationship.object == "github.create_issue"
    assert relationship.relation == "callers"
    assert relationship.subject_id == "User:u1"


@pytest.mark.asyncio
async def test_grant_exact_arguments_writes_tool_resource_relationship(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)
    monkeypatch.setattr(tool_access, "_assert_workspace_admin", AsyncMock())

    response = await grant_tool_access(
        ToolAccessGrantRequest(
            user_id="u1",
            tool_name="github.create_issue",
            arguments={"repo": "acme/app"},
        ),
        SimpleNamespace(workspace_id="ws1"),
    )

    assert response.grant.scope == "arguments"
    relationship = graph.write_tuple.await_args.args[0]
    assert relationship.namespace == "ToolResource"
    assert relationship.object.startswith("github.create_issue~args~")
    assert relationship.relation == "callers"
    assert relationship.subject_id == "User:u1"


@pytest.mark.asyncio
async def test_check_whole_tool_uses_tool_can_call(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: graph)

    response = await check_tool_access(
        ToolAccessCheckRequest(user_id="u1", tool_name="github.create_issue"),
        SimpleNamespace(workspace_id="ws1"),
    )

    assert response.allowed is True
    graph.check.assert_awaited_once_with(
        namespace="Tool",
        object="github.create_issue",
        relation="can_call",
        subject_id="User:u1",
    )


@pytest.mark.asyncio
async def test_check_exact_arguments_uses_runtime_invocation_helper(monkeypatch):
    monkeypatch.setattr(tool_access, "_openfga_graph", lambda: FakeGraph())
    helper = AsyncMock(return_value=True)
    monkeypatch.setattr(tool_access, "is_tool_invocation_allowed", helper)

    response = await check_tool_access(
        ToolAccessCheckRequest(
            user_id="u1",
            tool_name="github.create_issue",
            arguments={"repo": "acme/app"},
        ),
        SimpleNamespace(workspace_id="ws1"),
    )

    assert response.allowed is True
    helper.assert_awaited_once()
    assert helper.await_args.kwargs["user_id"] == "u1"
    assert helper.await_args.kwargs["tool_name"] == "github.create_issue"
    assert helper.await_args.kwargs["tool_args"] == {"repo": "acme/app"}
