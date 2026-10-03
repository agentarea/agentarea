from agentarea_execution.evaluation_mode import evaluation_context, evaluation_decision

TOOLSETS = {
    "agents": (None, {"list": "read", "update": "write"}),
    "shell": ("sandbox", {"bash": "destructive"}),
    "files": ("sandbox", {"read_file": "read", "save_file": "write"}),
}


def lookup():
    return TOOLSETS


def meta(**evaluation):
    return {"evaluation": {"run_id": "r", **evaluation}}


CONFIGURED = ("agentarea/agents", "agentarea/shell", "agentarea/files")


def decide(name, args=None, metadata=None, is_mcp=False, code_tools=CONFIGURED):
    return evaluation_decision(
        name,
        args or {},
        meta() if metadata is None else metadata,
        is_mcp=is_mcp,
        code_tools=code_tools,
        lookup=lookup,
    )


def test_an_ordinary_run_is_not_touched():
    assert decide("agents", {"action": "update"}, metadata={}) is None


def test_a_read_action_of_a_toolset_runs_for_real():
    assert decide("agents", {"action": "list"}).execute


def test_a_write_action_of_a_toolset_is_not_executed():
    decision = decide("agents", {"action": "update"})
    assert not decision.execute
    assert decision.stubbed is False
    assert "not executed" in decision.reason


def test_a_multi_method_toolset_without_an_action_is_not_executed():
    assert not decide("agents", {}).execute


def test_a_prefixed_method_name_is_understood():
    assert decide("agents_list").execute
    assert not decide("agents_update").execute


def test_a_stub_answers_instead_of_the_tool():
    decision = decide("agents", {"action": "update"}, metadata=meta(stubs={"agents": {"ok": True}}))
    assert not decision.execute
    assert decision.stubbed
    assert decision.result == {"ok": True}


def test_mcp_tools_never_run_for_real_without_a_stub():
    assert not decide("mcp__github__list_issues", is_mcp=True).execute


def test_sandbox_tools_run_only_when_the_run_allowed_the_sandbox():
    assert decide("shell", {"command": "ls"}, metadata=meta(sandbox_allowed=True)).execute
    assert not decide("shell", {"command": "ls"}).execute
    assert decide("files", {"action": "save_file"}, metadata=meta(sandbox_allowed=True)).execute


def test_an_unknown_tool_is_not_executed():
    assert not decide("mystery", metadata=meta(sandbox_allowed=True)).execute


def test_a_tool_that_only_shares_a_toolset_name_is_not_executed():
    # An OpenAPI operation called "agents" is not the platform toolset.
    assert not decide("agents", {"action": "list"}, code_tools=()).execute


def test_any_evaluation_marker_counts_and_fails_closed():
    assert evaluation_context({"evaluation": True}) == {}
    assert evaluation_context({"evaluation": {"stubs": {}}}) == {"stubs": {}}
    assert evaluation_context({"evaluation": None}) is None
    assert evaluation_context({}) is None
    assert not decide("agents", {"action": "update"}, metadata={"evaluation": True}).execute
