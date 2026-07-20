"""Unit tests for the disclosure-side view of the tool PDP.

Disclosure and enforcement must agree: a tool the gate would deny is never
offered to the model, so denied capabilities cannot pollute its context or be
attempted at all. Control-flow tools are not capabilities and are never gated,
so they must survive any policy.
"""

from agentarea_execution.workflows.helpers import (
    CONTROL_FLOW_TOOLS,
    ToolAction,
    decide_tool_action,
    filter_disclosed_tools,
    tool_definition_name,
)


def fn(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "parameters": {}}}


def names(tools: list[dict]) -> list[str]:
    return [tool_definition_name(t) or "" for t in tools]


def test_reads_both_tool_definition_shapes():
    assert tool_definition_name(fn("shell")) == "shell"
    assert tool_definition_name({"name": "shell"}) == "shell"
    assert tool_definition_name({}) is None


def test_denied_capability_is_never_disclosed():
    policy = {"tools": {"allowed": ["web_search"]}}
    tools = [fn("web_search"), fn("shell")]
    assert names(filter_disclosed_tools(policy, tools)) == ["web_search"]


def test_control_flow_tools_survive_even_an_explicit_deny():
    # Control-flow tools bypass the gate entirely: even a policy that denies them
    # by name must not strand the workflow — without completion the agent can
    # never finish, and without request_user_input it can never ask. A denied
    # capability tool (shell) is still excluded.
    policy = {"tools": {"denied": ["shell", *CONTROL_FLOW_TOOLS]}}
    tools = [fn(name) for name in sorted(CONTROL_FLOW_TOOLS)] + [fn("shell")]
    kept = names(filter_disclosed_tools(policy, tools))
    assert set(kept) == CONTROL_FLOW_TOOLS
    assert "shell" not in kept


def test_an_unrestricted_capability_tool_is_disclosed():
    # Default-allow: a composed tool with no restriction is offered to the model,
    # no allow rule required.
    assert names(filter_disclosed_tools({}, [fn("shell")])) == ["shell"]


def test_approval_required_tools_stay_disclosed():
    # The model may still call these; the gate escalates to a human instead of
    # rejecting, so hiding them would remove a capability the policy allows.
    policy = {"tools": {"allowed": ["shell"]}, "approval": {"escalation_rules": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.REQUIRE_APPROVAL
    assert names(filter_disclosed_tools(policy, [fn("shell")])) == ["shell"]


def test_disclosure_matches_the_gate_for_every_capability_tool():
    policy = {"tools": {"allowed": ["web_*"], "denied": ["web_admin"]}}
    tools = [fn("web_search"), fn("web_admin"), fn("shell")]
    disclosed = set(names(filter_disclosed_tools(policy, tools)))

    for tool in tools:
        name = tool_definition_name(tool) or ""
        gate_denies = decide_tool_action(policy, name) is ToolAction.DENY
        assert (name in disclosed) is not gate_denies


def test_glob_allowlist_is_honoured():
    policy = {"tools": {"allowed": ["web_*"]}}
    tools = [fn("web_search"), fn("web_fetch"), fn("shell")]
    assert names(filter_disclosed_tools(policy, tools)) == ["web_search", "web_fetch"]


def test_unnamed_definitions_are_dropped():
    assert filter_disclosed_tools({"tools": {"allowed": ["*"]}}, [{}]) == []


def test_order_is_preserved():
    policy = {"tools": {"allowed": ["*"]}}
    tools = [fn("completion"), fn("a"), fn("b")]
    assert names(filter_disclosed_tools(policy, tools)) == ["completion", "a", "b"]
