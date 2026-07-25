"""A tool must be able to say "I ran, and the work failed".

The wrapper used to stamp success=True on any method that returned without
raising, so the only way to report failure was to throw. A command exiting 1 is
not an exception — it is a normal return with a failing outcome, which left the
exit code buried in prose and every consumer believing the call succeeded.

MCP names this exact split: protocol errors (the tool could not run) travel one
channel, and tool execution errors — "the tool ran fine and the operation it
performed failed" — travel in the result itself so the model can self-correct.
"""

import json

import pytest

from agentarea_agents_sdk.tools.decorator_tool import Toolset, tool_method
from agentarea_agents_sdk.tools.tool_definition import toolset


@toolset(namespace="test/structured", display_name="S", description="d", category="utility")
class _StructuredToolset(Toolset):
    @tool_method
    async def run(self, code: int = 0) -> dict:
        """Return a structured outcome."""
        return {
            "success": code == 0,
            "result": f"exit_code: {code}",
            "exit_code": code,
            "outcome": "exit",
        }


@toolset(namespace="test/prose", display_name="P", description="d", category="utility")
class _ProseToolset(Toolset):
    @tool_method
    async def run(self) -> str:
        """Return plain text, as most tools do."""
        return "all good"


@toolset(namespace="test/raises", display_name="R", description="d", category="utility")
class _RaisingToolset(Toolset):
    @tool_method
    async def run(self) -> str:
        """Fail the way a tool that cannot run fails."""
        raise RuntimeError("could not start")


@pytest.mark.asyncio
async def test_a_structured_failure_is_not_overwritten_with_success():
    result = await _StructuredToolset().execute(code=1)

    assert result["success"] is False
    assert result["exit_code"] == 1


@pytest.mark.asyncio
async def test_a_structured_success_survives():
    result = await _StructuredToolset().execute(code=0)

    assert result["success"] is True
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_structured_results_keep_their_extra_fields():
    result = await _StructuredToolset().execute(code=2)

    assert result["outcome"] == "exit"
    assert result["result"] == "exit_code: 2"
    assert result["tool_name"]  # the wrapper still stamps its own fields


@pytest.mark.asyncio
async def test_a_prose_returning_tool_still_reports_success():
    # The common case must not change: a tool that returns text and does not
    # raise has succeeded.
    result = await _ProseToolset().execute()

    assert result["success"] is True
    assert result["result"] == "all good"


@pytest.mark.asyncio
async def test_a_raising_tool_is_still_a_failure():
    result = await _RaisingToolset().execute()

    assert result["success"] is False
    assert "could not start" in result["error"]


def test_shell_reports_the_exit_code_as_data():
    from agentarea_agents_sdk.tools.shell_toolset import _shell_outcome

    outcome = _shell_outcome({"exit_code": 1, "stdout": "", "stderr": "boom"})

    assert outcome["exit_code"] == 1
    assert outcome["success"] is False
    assert "boom" in outcome["result"]


def test_shell_success_is_derived_from_the_exit_code():
    from agentarea_agents_sdk.tools.shell_toolset import _shell_outcome

    assert _shell_outcome({"exit_code": 0, "stdout": "hi", "stderr": ""})["success"] is True
    assert _shell_outcome({"exit_code": 127, "stdout": "", "stderr": "nope"})["success"] is False


def test_shell_result_stays_readable_for_the_model():
    from agentarea_agents_sdk.tools.shell_toolset import _shell_outcome

    outcome = _shell_outcome({"exit_code": 0, "stdout": "hello", "stderr": ""})
    assert outcome["result"] == "hello"


def test_shell_artifacts_survive_alongside_the_outcome():
    from agentarea_agents_sdk.tools.shell_toolset import _shell_outcome

    outcome = _shell_outcome(
        {"exit_code": 0, "stdout": "{}", "stderr": ""},
        artifacts=[{"artifact_path": "sandbox/report.txt"}],
    )
    assert outcome["artifact_paths"] == ["sandbox/report.txt"]
    json.dumps(outcome)  # must stay serializable for the event payload
