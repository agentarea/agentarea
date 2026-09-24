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


def test_escalation_rules_match_the_same_patterns_the_allowlist_does():
    # `approval tool:send_*` compiles straight into escalation_rules, and the
    # write boundary accepts it, so matching it exactly made the rule install,
    # show up in the UI and never fire — an approval gate that was not there.
    policy = {"approval": {"escalation_rules": ["send_*"]}}

    assert decide_tool_policy(policy, "send_email").action is (
        ToolAuthorizationAction.REQUIRE_APPROVAL
    )
    assert decide_tool_policy(policy, "read_db").action is ToolAuthorizationAction.ALLOW


def test_a_non_empty_allowlist_still_restricts():
    policy = {"tools": {"allowed": ["web_*"]}}

    assert decide_tool_policy(policy, "web_search").action is ToolAuthorizationAction.ALLOW
    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.DENY


def test_an_absent_allowlist_restricts_nothing():
    """``to_json_dict`` drops ``allowed=None``, so the key is simply missing."""
    policy = {"tools": {"denied": []}}

    assert decide_tool_policy(policy, "shell_exec").action is ToolAuthorizationAction.ALLOW


def test_an_empty_allowlist_permits_no_tool():
    """``[]`` is the strictest allowlist, not the absence of one.

    Testing truthiness here made the empty allowlist permit every tool, which
    silently undid the one setting a policy author can use to say "no tools".
    """
    policy = {"tools": {"allowed": [], "denied": []}}

    assert decide_tool_policy(policy, "web_search").action is ToolAuthorizationAction.DENY
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


# --- aliases: one tool, several names a rule may target ------------------------

_MCP_SEARCH = ("mcp:3f2a:search", "search")


def test_rule_on_any_alias_governs_the_tool():
    by_canonical = {"tools": {"denied": ["mcp:3f2a:search"]}}
    by_raw = {"tools": {"denied": ["search"]}}
    by_model_name = {"tools": {"denied": ["mcp__github__*"]}}

    for policy in (by_canonical, by_raw, by_model_name):
        decision = decide_tool_policy(policy, "mcp__github__search", aliases=_MCP_SEARCH)
        assert decision.action is ToolAuthorizationAction.DENY


def test_canonical_rule_does_not_reach_the_same_tool_on_another_server():
    policy = {"approval": {"escalation_rules": ["mcp:3f2a:search"]}}

    other = decide_tool_policy(policy, "mcp__gitlab__search", aliases=("mcp:9c1b:search", "search"))

    assert other.action is ToolAuthorizationAction.ALLOW


def test_allowlist_admits_a_tool_named_by_any_alias():
    policy = {"tools": {"allowed": ["mcp:3f2a:*"]}}

    decision = decide_tool_policy(policy, "mcp__github__search", aliases=_MCP_SEARCH)

    assert decision.action is ToolAuthorizationAction.ALLOW


@pytest.mark.asyncio
async def test_invocation_request_carries_aliases():
    decision = await authorize_tool_invocation(
        ToolAuthorizationRequest(
            tool_name="mcp__github__search",
            tool_args={},
            effective_policy={"tools": {"denied": ["mcp:3f2a:search"]}},
            aliases=_MCP_SEARCH,
        )
    )

    assert decision.action is ToolAuthorizationAction.DENY
