"""Tests for the single tool invocation authorization PDP.

The resolved policy snapshot (composition + policy) is authoritative: disclosure,
the workflow gate, and the tool activity read one answer. ``decide_tool_policy``
is that judgment; ``authorize_tool_invocation`` is the request-shaped wrapper the
tool activity calls.
"""

import pytest
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
    authorize_tool_invocation,
    decide_tool_policy,
)

# --- decide_tool_policy: default-allow -----------------------------------------


def test_policy_allows_an_unrestricted_composed_tool():
    # A composed tool with no governing policy is allowed — deny-by-default is gone.
    assert decide_tool_policy(None, "web_search").action is ToolAuthorizationAction.ALLOW
    assert decide_tool_policy({}, "web_search").action is ToolAuthorizationAction.ALLOW


def test_policy_deny_beats_allowlist_and_approval():
    policy = {
        "tools": {"allowed": ["*"], "denied": ["shell_exec"]},
        "approval": {"requires_human_approval": True},
    }

    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.DENY


def test_policy_escalation_requires_approval():
    policy = {"approval": {"escalation_rules": ["shell_exec"]}}

    assert decide_tool_policy(policy, "shell_exec").action is (
        ToolAuthorizationAction.REQUIRE_APPROVAL
    )


def test_a_non_empty_allowlist_still_restricts():
    policy = {"tools": {"allowed": ["web_*"]}}

    assert decide_tool_policy(policy, "web_search").action is ToolAuthorizationAction.ALLOW
    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.DENY


# --- authorize_tool_invocation: the request-shaped policy verdict ---------------


@pytest.mark.asyncio
async def test_authorize_returns_the_policy_decision():
    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="web_search",
            tool_args={"query": "x"},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"allowed": ["web_*"]}},
        )
    )

    assert decision.action is ToolAuthorizationAction.ALLOW


@pytest.mark.asyncio
async def test_authorize_denies_a_policy_denied_tool():
    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="shell",
            tool_args={},
            user_id="u1",
            workspace_id="ws-1",
            effective_policy={"tools": {"denied": ["shell"]}},
        )
    )

    assert decision.action is ToolAuthorizationAction.DENY


@pytest.mark.asyncio
async def test_authorize_allows_when_no_policy_restricts():
    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(tool_name="shell", tool_args={}, effective_policy=None)
    )

    assert decision.action is ToolAuthorizationAction.ALLOW
