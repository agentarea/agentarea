"""Tests for exact tool invocation authorization helpers."""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.tool_invocation import (
    is_tool_invocation_allowed,
    tool_object_id,
    tool_resource_link_tuple,
    tool_resource_object_id,
    tool_resource_workspace_tuple,
    tool_workspace_tuple,
)
from agentarea_common.rebac.models import CheckResult
from agentarea_common.rebac.openfga_client import OpenFGAError


def test_tool_resource_id_is_stable_for_canonical_args():
    first = tool_resource_object_id(
        "github.create_issue", {"title": "Bug", "repo": "acme/app"}, "ws-1"
    )
    second = tool_resource_object_id(
        "github.create_issue", {"repo": "acme/app", "title": "Bug"}, "ws-1"
    )
    different = tool_resource_object_id(
        "github.create_issue", {"repo": "acme/other", "title": "Bug"}, "ws-1"
    )

    assert first == second
    assert first != different
    assert first.startswith("ws-1/github.create_issue~args~")


def test_tool_names_are_url_safe_object_ids():
    assert tool_object_id("github/create issue") == "github%2Fcreate%20issue"
    assert tool_object_id("github/create issue", "ws/1") == "ws%2F1/github%2Fcreate%20issue"


def test_tool_resource_link_tuple_points_exact_resource_to_broad_tool():
    tuple_ = tool_resource_link_tuple("github.create_issue", {"repo": "acme/app"}, "ws-1")
    assert tuple_.namespace == "ToolResource"
    assert tuple_.relation == "tool"
    assert tuple_.subject_id == "Tool:ws-1/github.create_issue"


def test_tool_workspace_tuples_attach_resources_to_workspace():
    tool_tuple = tool_workspace_tuple("github.create_issue", "ws-1")
    resource_tuple = tool_resource_workspace_tuple(
        "github.create_issue", {"repo": "acme/app"}, "ws-1"
    )

    assert tool_tuple.namespace == "Tool"
    assert tool_tuple.object == "ws-1/github.create_issue"
    assert tool_tuple.relation == "workspace"
    assert tool_tuple.subject_id == "Workspace:ws-1"
    assert resource_tuple.namespace == "ToolResource"
    assert resource_tuple.object.startswith("ws-1/github.create_issue~args~")
    assert resource_tuple.relation == "workspace"
    assert resource_tuple.subject_id == "Workspace:ws-1"


@pytest.mark.asyncio
async def test_invocation_check_uses_user_and_contextual_tool_link():
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=True)

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id="u1",
        workspace_id="ws-1",
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is True
    openfga.check.assert_awaited_once()
    kwargs = openfga.check.await_args.kwargs
    assert kwargs["namespace"] == "ToolResource"
    assert kwargs["object"].startswith("ws-1/github.create_issue~args~")
    assert kwargs["relation"] == "can_call"
    assert kwargs["subject_id"] == "User:u1"
    assert [tuple_.relation for tuple_ in kwargs["contextual_tuples"]] == [
        "members",
        "workspace",
        "workspace",
        "tool",
    ]


@pytest.mark.asyncio
async def test_invocation_without_workspace_denies_without_openfga_call():
    openfga = AsyncMock()

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id="u1",
        workspace_id=None,
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is False
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_invocation_workspace_model_error_does_not_retry_weaker_check():
    openfga = AsyncMock()
    openfga.check.side_effect = OpenFGAError("unknown relation workspace")

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id="u1",
        workspace_id="ws-1",
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is False
    openfga.check.assert_awaited_once()


@pytest.mark.asyncio
async def test_invocation_without_user_denies_without_openfga_call():
    openfga = AsyncMock()

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id=None,
        workspace_id="ws-1",
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is False
    openfga.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_invocation_openfga_error_fails_closed():
    openfga = AsyncMock()
    openfga.check.side_effect = OpenFGAError("down")

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id="u1",
        workspace_id="ws-1",
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is False
