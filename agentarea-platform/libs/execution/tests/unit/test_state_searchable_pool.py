"""AgentExecutionState + ContinueAsNewState carry searchable_tool_pool and revealed_openapi_tools."""

from agentarea_execution.workflows.models import (
    AgentExecutionState,
    AgentGoal,
    ContinueAsNewState,
)


def _goal():
    return AgentGoal(
        id="g",
        description="d",
        success_criteria=[],
        max_iterations=1,
        requires_human_approval=False,
        context={},
    )


def test_agent_state_defaults_empty_pool_and_revealed():
    s = AgentExecutionState()
    assert s.searchable_tool_pool == []
    assert s.revealed_openapi_tools == []


def test_continue_as_new_state_defaults_empty_pool_and_revealed():
    s = ContinueAsNewState(
        execution_id="e",
        agent_id="a",
        task_id="t",
        user_id="u",
        workspace_id="w",
        goal=_goal(),
        messages=[],
        agent_config={},
        available_tools=[],
        current_iteration=0,
    )
    assert s.searchable_tool_pool == []
    assert s.revealed_openapi_tools == []


def test_agent_state_round_trips_pool_through_pydantic():
    pool = [
        {
            "name": "createCharge",
            "description": "Create a charge.",
            "connection_id": "conn-1",
            "schema": {"type": "function", "function": {"name": "createCharge"}},
            "source_type": "openapi",
        }
    ]
    s = AgentExecutionState(
        searchable_tool_pool=pool,
        revealed_openapi_tools=["createCharge"],
    )
    dumped = s.model_dump()
    rehydrated = AgentExecutionState(**dumped)
    assert rehydrated.searchable_tool_pool == pool
    assert rehydrated.revealed_openapi_tools == ["createCharge"]


def test_continue_as_new_round_trips_pool():
    pool = [{"name": "x", "description": "y", "connection_id": "c", "schema": {}, "source_type": "openapi"}]
    s = ContinueAsNewState(
        execution_id="e",
        agent_id="a",
        task_id="t",
        user_id="u",
        workspace_id="w",
        goal=_goal(),
        messages=[],
        agent_config={},
        available_tools=[],
        current_iteration=0,
        searchable_tool_pool=pool,
        revealed_openapi_tools=["x"],
    )
    dumped = s.model_dump()
    rehydrated = ContinueAsNewState(**dumped)
    assert rehydrated.searchable_tool_pool == pool
    assert rehydrated.revealed_openapi_tools == ["x"]
