"""Continue-as-new round-trip for searchable OpenAPI pool + revealed names (issue #115).

Workflow methods that touch `workflow.logger` only run inside Temporal's
event loop. We monkey-patch the module-level `workflow` symbol with a stub
so we can exercise pure state-mutation logic in plain unit tests.
"""

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from agentarea_execution.workflows import agent_execution_workflow as wf_mod
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.models import AgentGoal, ContinueAsNewState


@pytest.fixture(autouse=True)
def stub_workflow_logger(monkeypatch):
    """Patch temporalio's workflow.logger so plain test loops don't hit the sandbox."""
    import temporalio.workflow as _temporal_workflow

    fake_logger = logging.getLogger("test_continue_as_new_stub")
    monkeypatch.setattr(_temporal_workflow, "logger", fake_logger)
    yield


def _goal():
    return AgentGoal(
        id="g",
        description="d",
        success_criteria=[],
        max_iterations=1,
        requires_human_approval=False,
        context={},
    )


def _pool_entry(name: str):
    return {
        "name": name,
        "description": f"Operation {name}",
        "connection_id": "stripe-conn",
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": f"Operation {name}",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        "source_type": "openapi",
    }


def test_continue_as_new_round_trips_searchable_state():
    """ContinueAsNewState carries pool + revealed list verbatim; _restore_from_continued_state
    re-instantiates the disclosure policy and surfaces both fields on the new state."""
    pool = [_pool_entry("op_01"), _pool_entry("op_02")]
    revealed_schema = pool[0]["schema"]

    cstate = ContinueAsNewState(
        execution_id="exec-1",
        agent_id="agent-1",
        task_id="task-1",
        user_id="user-1",
        workspace_id="ws-1",
        goal=_goal(),
        messages=[],
        agent_config={"model_id": "x"},
        # available_tools carries the previously revealed schema verbatim, just like
        # the pre-continue-as-new state did.
        available_tools=[
            {"type": "function", "function": {"name": "completion", "parameters": {}}},
            revealed_schema,
        ],
        current_iteration=12,
        searchable_tool_pool=pool,
        revealed_openapi_tools=["op_01"],
    )

    wf = AgentExecutionWorkflow()
    # _restore is async only because of workflow.logger; works synchronously here too.
    asyncio.run(wf._restore_from_continued_state(cstate.model_dump()))

    assert wf.state.searchable_tool_pool == pool
    assert wf.state.revealed_openapi_tools == ["op_01"]
    # Disclosure policy reinstantiated because pool is non-empty.
    assert wf._disclosure_policy is not None
    # The previously revealed schema is still callable as a regular tool.
    schema_names = [
        t["function"]["name"]
        for t in wf.state.available_tools
        if t.get("type") == "function"
    ]
    assert "op_01" in schema_names


def test_continue_as_new_drops_stale_revealed_names_when_pool_shrinks():
    """If a previously revealed operation is no longer in the rebuilt pool
    (connection edited mid-task), restore must drop it from revealed_openapi_tools
    AND from available_tools — otherwise the LLM sees a tool it can no longer call.
    """
    surviving = _pool_entry("op_keep")
    cstate = ContinueAsNewState(
        execution_id="exec-1",
        agent_id="agent-1",
        task_id="task-1",
        user_id="user-1",
        workspace_id="ws-1",
        goal=_goal(),
        messages=[],
        agent_config={},
        # available_tools carries TWO previously revealed schemas, but the new pool
        # only contains one of them.
        available_tools=[
            {"type": "function", "function": {"name": "completion", "parameters": {}}},
            surviving["schema"],
            {
                "type": "function",
                "function": {
                    "name": "op_gone",
                    "description": "removed",
                    "parameters": {"type": "object"},
                },
            },
        ],
        current_iteration=2,
        searchable_tool_pool=[surviving],
        revealed_openapi_tools=["op_keep", "op_gone"],
    )
    wf = AgentExecutionWorkflow()
    asyncio.run(wf._restore_from_continued_state(cstate.model_dump()))

    assert wf.state.revealed_openapi_tools == ["op_keep"]
    schema_names = [
        t["function"]["name"]
        for t in wf.state.available_tools
        if t.get("type") == "function"
    ]
    assert "op_keep" in schema_names
    assert "op_gone" not in schema_names


def test_continue_as_new_with_empty_pool_leaves_policy_unset():
    cstate = ContinueAsNewState(
        execution_id="exec-1",
        agent_id="agent-1",
        task_id="task-1",
        user_id="user-1",
        workspace_id="ws-1",
        goal=_goal(),
        messages=[],
        agent_config={},
        available_tools=[],
        current_iteration=0,
    )
    wf = AgentExecutionWorkflow()
    asyncio.run(wf._restore_from_continued_state(cstate.model_dump()))
    assert wf.state.searchable_tool_pool == []
    assert wf.state.revealed_openapi_tools == []
    assert wf._disclosure_policy is None
