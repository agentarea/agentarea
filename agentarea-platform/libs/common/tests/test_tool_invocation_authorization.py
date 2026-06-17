"""Tests for exact tool invocation authorization helpers."""

from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.tool_invocation import (
    is_tool_invocation_allowed,
    tool_object_id,
    tool_resource_link_tuple,
    tool_resource_object_id,
)
from agentarea_common.rebac.models import CheckResult
from agentarea_common.rebac.openfga_client import OpenFGAError


def test_tool_resource_id_is_stable_for_canonical_args():
    first = tool_resource_object_id("github.create_issue", {"title": "Bug", "repo": "acme/app"})
    second = tool_resource_object_id("github.create_issue", {"repo": "acme/app", "title": "Bug"})
    different = tool_resource_object_id("github.create_issue", {"repo": "acme/other", "title": "Bug"})

    assert first == second
    assert first != different
    assert first.startswith("github.create_issue:args:")


def test_tool_names_are_url_safe_object_ids():
    assert tool_object_id("github/create issue") == "github%2Fcreate%20issue"


def test_tool_resource_link_tuple_points_exact_resource_to_broad_tool():
    tuple_ = tool_resource_link_tuple("github.create_issue", {"repo": "acme/app"})
    assert tuple_.namespace == "ToolResource"
    assert tuple_.relation == "tool"
    assert tuple_.subject_id == "Tool:github.create_issue"


@pytest.mark.asyncio
async def test_invocation_check_uses_user_and_contextual_tool_link():
    openfga = AsyncMock()
    openfga.check.return_value = CheckResult(allowed=True)

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id="u1",
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is True
    openfga.check.assert_awaited_once()
    kwargs = openfga.check.await_args.kwargs
    assert kwargs["namespace"] == "ToolResource"
    assert kwargs["relation"] == "can_call"
    assert kwargs["subject_id"] == "User:u1"
    assert kwargs["contextual_tuples"][0].relation == "tool"


@pytest.mark.asyncio
async def test_invocation_without_user_denies_without_openfga_call():
    openfga = AsyncMock()

    allowed = await is_tool_invocation_allowed(
        openfga,
        user_id=None,
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
        tool_name="github.create_issue",
        tool_args={"repo": "acme/app"},
    )

    assert allowed is False
