"""Tests for effective policy propagation model contracts."""

import inspect
from uuid import uuid4

from agentarea_execution.models import (
    AgentExecutionRequest,
    LLMCallRequest,
    MCPToolRequest,
)
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_execution.workflows.constants import LLM_CALL_TIMEOUT, LLM_RETRY_ATTEMPTS
from agentarea_execution.workflows.models import (
    AgentExecutionState,
    AgentGoal,
    ContinueAsNewState,
)
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor


def _effective_policy() -> dict:
    return {
        "budget": {"run_budget_usd": "1.25"},
        "tokens": {"max_tokens": 1000},
        "tools": {"allowed": ["github_*"], "denied": ["delete_*"]},
    }


def test_agent_execution_request_accepts_effective_policy():
    policy = _effective_policy()
    request = AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=uuid4(),
        user_id="user-1",
        workspace_id="workspace-1",
        task_query="do work",
        effective_policy=policy,
    )

    assert request.effective_policy == policy


def test_workflow_state_and_continue_as_new_preserve_effective_policy():
    policy = _effective_policy()
    goal = AgentGoal(
        id="goal-1",
        description="do work",
        success_criteria=[],
        max_iterations=1,
        requires_human_approval=False,
        context={},
    )

    state = AgentExecutionState(
        execution_id="exec-1",
        agent_id="agent-1",
        task_id="task-1",
        user_id="user-1",
        workspace_id="workspace-1",
        goal=goal,
        effective_policy=policy,
    )
    continued = ContinueAsNewState(
        execution_id=state.execution_id,
        agent_id=state.agent_id,
        task_id=state.task_id,
        user_id=state.user_id,
        workspace_id=state.workspace_id,
        goal=goal,
        messages=[],
        agent_config={},
        available_tools=[],
        current_iteration=state.current_iteration,
        effective_policy=state.effective_policy,
    )

    assert continued.effective_policy == policy


def test_activity_requests_accept_effective_policy():
    policy = _effective_policy()

    llm_request = LLMCallRequest(
        messages=[],
        model_id="model-1",
        effective_policy=policy,
    )
    mcp_request = MCPToolRequest(
        tool_name="github_create_issue",
        tool_args={},
        workspace_id="workspace-1",
        effective_policy=policy,
    )

    assert llm_request.effective_policy == policy
    assert mcp_request.effective_policy == policy


def test_workflow_initialization_stores_effective_policy_from_request():
    source = inspect.getsource(AgentExecutionWorkflow._initialize_workflow)

    assert "self.state.effective_policy = request.effective_policy" in source


def test_temporal_executor_passes_effective_policy_to_agent_execution_request():
    source = inspect.getsource(TemporalWorkflowExecutor.start_workflow)

    assert 'effective_policy=args.get("effective_policy")' in source


def test_workflow_goal_uses_request_max_reasoning_iterations_by_default():
    request = AgentExecutionRequest(
        task_id=uuid4(),
        agent_id=uuid4(),
        user_id="user-1",
        workspace_id="workspace-1",
        task_query="do work",
        max_reasoning_iterations=7,
    )

    workflow_obj = AgentExecutionWorkflow()
    goal = workflow_obj._build_goal_from_request(request)

    assert goal.max_iterations == 7


def test_workflow_iteration_limit_allows_configured_final_iteration():
    source = inspect.getsource(AgentExecutionWorkflow._should_continue_execution)

    assert "self.state.current_iteration > max_iterations" in source


def test_llm_activity_timeout_allows_large_generations_without_retries():
    assert LLM_CALL_TIMEOUT.total_seconds() == 600
    assert LLM_RETRY_ATTEMPTS == 1


def test_workflow_continue_as_new_and_activity_payloads_carry_effective_policy():
    source = inspect.getsource(AgentExecutionWorkflow)

    assert "ContinueAsNewState(" in source
    assert "effective_policy=self.state.effective_policy" in source
    assert "LLMCallRequest(" in source
    assert "MCPToolRequest(" in source
