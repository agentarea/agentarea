from agentarea_execution.evaluation_mode import evaluation_decision

EFFECTS = {
    "agents_list": ("platform", "read"),
    "agents_update": ("platform", "write"),
    "shell_bash": ("sandbox", "destructive"),
    "files_save_file": ("sandbox", "write"),
}


def lookup():
    return EFFECTS


def meta(**evaluation):
    return {"evaluation": {"run_id": "r", **evaluation}}


def test_an_ordinary_run_is_not_touched():
    assert evaluation_decision("agents_update", {}, is_mcp=False, lookup=lookup) is None


def test_a_read_tool_runs_for_real():
    decision = evaluation_decision("agents_list", meta(), is_mcp=False, lookup=lookup)
    assert decision.execute


def test_a_write_tool_is_not_executed():
    decision = evaluation_decision("agents_update", meta(), is_mcp=False, lookup=lookup)
    assert not decision.execute
    assert decision.stubbed is False
    assert "not executed" in decision.reason


def test_a_stub_answers_instead_of_the_tool():
    decision = evaluation_decision(
        "agents_update", meta(stubs={"agents_update": {"ok": True}}), is_mcp=False, lookup=lookup
    )
    assert not decision.execute
    assert decision.stubbed
    assert decision.result == {"ok": True}


def test_mcp_tools_never_run_for_real_without_a_stub():
    decision = evaluation_decision("mcp__github__list_issues", meta(), is_mcp=True, lookup=lookup)
    assert not decision.execute


def test_sandbox_tools_run_only_when_the_run_allowed_the_sandbox():
    allowed = evaluation_decision("shell_bash", meta(sandbox_allowed=True), is_mcp=False, lookup=lookup)
    denied = evaluation_decision("shell_bash", meta(), is_mcp=False, lookup=lookup)

    assert allowed.execute
    assert not denied.execute


def test_an_unknown_tool_is_not_executed():
    decision = evaluation_decision("mystery_tool", meta(sandbox_allowed=True), is_mcp=False, lookup=lookup)
    assert not decision.execute
